"""求解ジョブ。

要件書 2.1 の実測どおり、高校規模では求解に25秒かかることがあり、HTTPリクエストの
中で待たせられない。一方で必要なのは「リクエストの外に出すこと」だけなので、
分散ワーカーは使わずスレッドプールとプロセス内のジョブ表で済ませる（仮定 A-06）。
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from . import models as m
from . import services
from .db import SessionLocal
from .solver.engine import DEFAULT_TIME_LIMIT_SEC, LockConflictError, solve

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


@dataclass
class SolveJob:
    id: str
    school_id: int
    source_timetable_id: int | None
    time_limit_sec: int
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    timetable_id: int | None = None
    error: str | None = None
    violations: list[dict] = field(default_factory=list)
    unmet_periods: int | None = None
    total_periods: int | None = None
    solver_status: str | None = None
    timed_out: bool = False
    stats: dict = field(default_factory=dict)

    @property
    def elapsed_sec(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.time()
        return end - self.started_at

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "school_id": self.school_id,
            "status": self.status,
            "elapsed_sec": round(self.elapsed_sec, 2),
            "timetable_id": self.timetable_id,
            "error": self.error,
            "violations": self.violations,
            "unmet_periods": self.unmet_periods,
            "total_periods": self.total_periods,
            "solver_status": self.solver_status,
            "timed_out": self.timed_out,
            "stats": self.stats,
        }


class JobRegistry:
    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, SolveJob] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def get(self, job_id: str) -> SolveJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[SolveJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> bool:
        """キャンセルする。

        CBC の求解自体は中断できないため、結果を保存しないことで実現する（仮定 A-22）。
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in ("succeeded", "failed", "cancelled"):
                return False
            self._cancelled.add(job_id)
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = time.time()
            return True

    def submit(
        self,
        school_id: int,
        source_timetable_id: int | None,
        time_limit_sec: int = DEFAULT_TIME_LIMIT_SEC,
        name: str | None = None,
    ) -> SolveJob:
        job = SolveJob(
            id=uuid.uuid4().hex[:12],
            school_id=school_id,
            source_timetable_id=source_timetable_id,
            time_limit_sec=time_limit_sec,
        )
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job, name)
        return job

    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def _run(self, job: SolveJob, name: str | None) -> None:
        if self._is_cancelled(job.id):
            return
        job.status = "running"
        job.started_at = time.time()
        db = SessionLocal()
        try:
            school = db.get(m.School, job.school_id)
            if school is None:
                raise ValueError("学校が見つかりません")
            source = (
                db.get(m.Timetable, job.source_timetable_id)
                if job.source_timetable_id
                else None
            )
            spec = services.build_spec(db, school, source)
            result = solve(spec, time_limit_sec=job.time_limit_sec)

            if self._is_cancelled(job.id):
                job.status = "cancelled"
                job.finished_at = time.time()
                return

            timetable = m.Timetable(
                school_id=school.id,
                name=name or _default_name(db, school),
                parent_id=source.id if source else None,
            )
            db.add(timetable)
            db.flush()
            # 新しい版では、元の版で固定されていた割当のロックを引き継ぐ
            if source is not None:
                locked = {(a.course_id, a.day, a.period) for a in source.assignments if a.locked}
            else:
                locked = set()
            for pl in result.placements:
                db.add(
                    m.Assignment(
                        timetable_id=timetable.id,
                        course_id=pl.course_id,
                        day=pl.day,
                        period=pl.period,
                        locked=(pl.course_id, pl.day, pl.period) in locked,
                    )
                )
            db.commit()

            job.timetable_id = timetable.id
            job.violations = [v.as_dict() for v in result.violations]
            job.unmet_periods = result.unmet_periods
            job.total_periods = result.total_periods
            job.solver_status = result.status
            job.timed_out = result.timed_out
            job.stats = result.stats
            job.status = "succeeded"
        except LockConflictError as exc:
            db.rollback()
            job.status = "failed"
            job.error = "固定された割当に矛盾があるため求解できません。固定を外してください。"
            job.violations = [v.as_dict() for v in exc.violations]
        except Exception as exc:  # noqa: BLE001 - ジョブの失敗理由をそのまま伝える
            db.rollback()
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = time.time()
            db.close()


def _default_name(db, school: m.School) -> str:
    count = db.query(m.Timetable).filter(m.Timetable.school_id == school.id).count()
    return f"提案 v{count + 1}"


registry = JobRegistry()
