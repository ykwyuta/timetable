"""HTTP API。

求解は非同期（ジョブID＋ポーリング）、検証は同期。要件書 2.1 の実測に基づく。
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import curriculum as cur
from . import models as m
from . import services
from .db import get_db
from .jobs import registry
from .solver.constraints import CONSTRAINT_INFO, DAY_NAMES
from .solver.engine import DEFAULT_TIME_LIMIT_SEC, validate
from .solver.spec import Placement

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# リクエストの型
# ---------------------------------------------------------------------------


class SchoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    school_type: str
    classes_per_grade: int = Field(ge=1, le=12)
    include_special_needs: bool = False


class SolveRequest(BaseModel):
    source_timetable_id: int | None = None
    time_limit_sec: int = Field(default=DEFAULT_TIME_LIMIT_SEC, ge=1, le=600)
    name: str | None = None


class AssignmentCreate(BaseModel):
    course_id: int
    day: int = Field(ge=0, le=6)
    period: int = Field(ge=0, le=11)


class AssignmentMove(BaseModel):
    day: int = Field(ge=0, le=6)
    period: int = Field(ge=0, le=11)


class LockUpdate(BaseModel):
    locked: bool


class AssignmentItem(BaseModel):
    course_id: int
    day: int
    period: int
    locked: bool = False


class AssignmentsReplace(BaseModel):
    """時間割の割当をまとめて置き換える。フロントの undo/redo が使う。"""

    assignments: list[AssignmentItem]


class TeacherUpdate(BaseModel):
    max_weekly_periods: int | None = Field(default=None, ge=1, le=40)
    unavailable: list[AssignmentMove] | None = None


# ---------------------------------------------------------------------------
# シリアライズ
# ---------------------------------------------------------------------------


def _school_dict(school: m.School) -> dict:
    return {
        "id": school.id,
        "name": school.name,
        "school_type": school.school_type,
        "school_type_label": cur.SCHOOL_TYPE_LABELS[school.school_type],
        "days": school.days,
        "periods_per_day": school.periods_per_day,
        "period_minutes": school.period_minutes,
        "day_names": DAY_NAMES[: school.days],
    }


def _timetable_payload(db: Session, timetable: m.Timetable) -> dict:
    school = timetable.school
    spec = services.build_spec(db, school, timetable)
    placements = services.placements_of(timetable)
    violations = validate(spec, placements)

    group_of = spec.group_of_course
    courses = []
    placed_counts: dict[int, int] = {}
    for a in timetable.assignments:
        placed_counts[a.course_id] = placed_counts.get(a.course_id, 0) + 1
    for c in db.query(m.Course).filter(m.Course.school_id == school.id).all():
        courses.append(
            {
                "id": c.id,
                "subject_id": c.subject_id,
                "subject_name": c.subject.name,
                "short_name": c.subject.short_name,
                "is_core": bool(c.subject.is_core),
                "room_type": c.subject.room_type,
                "teacher_id": c.teacher_id,
                "teacher_name": c.teacher.name,
                "class_ids": [k.id for k in c.classes],
                "weekly_periods": c.weekly_periods,
                "max_per_day": c.max_per_day,
                "prefers_double": bool(c.prefers_double),
                "group_id": group_of.get(c.id),
                "placed": placed_counts.get(c.id, 0),
            }
        )

    unplaced = [
        {"course_id": c["id"], "remaining": c["weekly_periods"] - c["placed"]}
        for c in courses
        if c["weekly_periods"] > c["placed"]
    ]

    return {
        "id": timetable.id,
        "name": timetable.name,
        "parent_id": timetable.parent_id,
        "created_at": timetable.created_at.isoformat(),
        "school": _school_dict(school),
        "classes": [
            {"id": k.id, "name": k.name, "grade": k.grade, "kind": k.kind}
            for k in sorted(
                db.query(m.SchoolClass).filter(m.SchoolClass.school_id == school.id).all(),
                key=lambda k: (k.kind != "normal", k.grade, k.name),
            )
        ],
        "teachers": [
            {
                "id": t.id,
                "name": t.name,
                "kind": t.kind,
                "max_weekly_periods": t.max_weekly_periods,
                "unavailable": [{"day": u.day, "period": u.period} for u in t.unavailabilities],
            }
            for t in db.query(m.Teacher).filter(m.Teacher.school_id == school.id).all()
        ],
        "courses": courses,
        "parallel_groups": [
            {"id": g.id, "name": g.name, "course_ids": [c.id for c in g.courses]}
            for g in db.query(m.ParallelGroup)
            .filter(m.ParallelGroup.school_id == school.id)
            .all()
        ],
        "blocked_slots": [
            {"class_id": b.class_id, "day": b.day, "period": b.period, "reason": b.reason}
            for b in db.query(m.BlockedSlot)
            .filter(m.BlockedSlot.school_id == school.id)
            .all()
        ],
        "assignments": [
            {
                "id": a.id,
                "course_id": a.course_id,
                "day": a.day,
                "period": a.period,
                "locked": bool(a.locked),
            }
            for a in sorted(timetable.assignments, key=lambda a: (a.day, a.period, a.id))
        ],
        "violations": [v.as_dict() for v in violations],
        "unplaced": unplaced,
        "summary": {
            "total_periods": sum(c["weekly_periods"] for c in courses),
            "placed_periods": len(timetable.assignments),
            "unmet_periods": sum(u["remaining"] for u in unplaced),
            "hard_violations": sum(1 for v in violations if v.severity == "hard"),
            "soft_violations": sum(1 for v in violations if v.severity == "soft"),
            "locked": sum(1 for a in timetable.assignments if a.locked),
        },
    }


def _get_timetable(db: Session, timetable_id: int) -> m.Timetable:
    tt = db.get(m.Timetable, timetable_id)
    if tt is None:
        raise HTTPException(status_code=404, detail="時間割が見つかりません")
    return tt


# ---------------------------------------------------------------------------
# メタ情報
# ---------------------------------------------------------------------------


@router.get("/meta")
def get_meta() -> dict:
    """校種の選択肢と、週コマ数の内訳。画面の初期表示に使う。"""
    school_types = []
    for st, label in cur.SCHOOL_TYPE_LABELS.items():
        grades = []
        for g in cur.GRADES[st]:
            weekly = cur.weekly_periods_for(st, g)
            electives = [
                {"name": name, "periods": n, "subjects": subs}
                for name, n, subs in cur.HIGH_ELECTIVES.get(g, [])
            ] if st == cur.HIGH else []
            grades.append(
                {
                    "grade": g,
                    "weekly": weekly,
                    "electives": electives,
                    "total": cur.total_weekly_periods(st, g),
                }
            )
        school_types.append(
            {
                "value": st,
                "label": label,
                "period_minutes": cur.PERIOD_MINUTES[st],
                "periods_per_day": cur.PERIODS_PER_DAY[st],
                "grades": grades,
            }
        )
    return {
        "school_types": school_types,
        "constraints": CONSTRAINT_INFO,
        "max_classes": services.MAX_CLASSES,
        "day_names": DAY_NAMES[:5],
    }


# ---------------------------------------------------------------------------
# 学校
# ---------------------------------------------------------------------------


@router.get("/schools")
def list_schools(db: Session = Depends(get_db)) -> list[dict]:
    schools = db.query(m.School).order_by(m.School.id.desc()).all()
    out = []
    for s in schools:
        out.append(
            {
                **_school_dict(s),
                "class_count": db.query(m.SchoolClass)
                .filter(m.SchoolClass.school_id == s.id)
                .count(),
                "course_count": db.query(m.Course).filter(m.Course.school_id == s.id).count(),
                "timetable_count": db.query(m.Timetable)
                .filter(m.Timetable.school_id == s.id)
                .count(),
            }
        )
    return out


@router.post("/schools", status_code=201)
def create_school(payload: SchoolCreate, db: Session = Depends(get_db)) -> dict:
    try:
        school = services.generate_school(
            db,
            name=payload.name,
            school_type=payload.school_type,
            classes_per_grade=payload.classes_per_grade,
            include_special_needs=payload.include_special_needs,
        )
    except services.GenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **_school_dict(school),
        "class_count": len(school.classes),
        "course_count": len(school.courses),
        "timetable_count": 0,
    }


@router.delete("/schools/{school_id}", status_code=204)
def delete_school(school_id: int, db: Session = Depends(get_db)) -> Response:
    school = db.get(m.School, school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="学校が見つかりません")
    db.delete(school)
    db.commit()
    return Response(status_code=204)


@router.get("/schools/{school_id}/timetables")
def list_timetables(school_id: int, db: Session = Depends(get_db)) -> list[dict]:
    if db.get(m.School, school_id) is None:
        raise HTTPException(status_code=404, detail="学校が見つかりません")
    rows = (
        db.query(m.Timetable)
        .filter(m.Timetable.school_id == school_id)
        .order_by(m.Timetable.id.desc())
        .all()
    )
    return [
        {
            "id": t.id,
            "name": t.name,
            "parent_id": t.parent_id,
            "created_at": t.created_at.isoformat(),
            "assignment_count": len(t.assignments),
        }
        for t in rows
    ]


@router.patch("/teachers/{teacher_id}")
def update_teacher(
    teacher_id: int, payload: TeacherUpdate, db: Session = Depends(get_db)
) -> dict:
    teacher = db.get(m.Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=404, detail="教員が見つかりません")
    if payload.max_weekly_periods is not None:
        teacher.max_weekly_periods = payload.max_weekly_periods
    if payload.unavailable is not None:
        for u in list(teacher.unavailabilities):
            db.delete(u)
        db.flush()
        for slot in payload.unavailable:
            db.add(
                m.TeacherUnavailability(
                    teacher_id=teacher.id, day=slot.day, period=slot.period
                )
            )
    db.commit()
    db.refresh(teacher)
    return {
        "id": teacher.id,
        "name": teacher.name,
        "kind": teacher.kind,
        "max_weekly_periods": teacher.max_weekly_periods,
        "unavailable": [{"day": u.day, "period": u.period} for u in teacher.unavailabilities],
    }


# ---------------------------------------------------------------------------
# 求解ジョブ
# ---------------------------------------------------------------------------


@router.post("/schools/{school_id}/solve", status_code=202)
def start_solve(school_id: int, payload: SolveRequest, db: Session = Depends(get_db)) -> dict:
    if db.get(m.School, school_id) is None:
        raise HTTPException(status_code=404, detail="学校が見つかりません")
    if payload.source_timetable_id is not None:
        source = db.get(m.Timetable, payload.source_timetable_id)
        if source is None or source.school_id != school_id:
            raise HTTPException(status_code=404, detail="元の時間割が見つかりません")
    job = registry.submit(
        school_id=school_id,
        source_timetable_id=payload.source_timetable_id,
        time_limit_sec=payload.time_limit_sec,
        name=payload.name,
    )
    return job.as_dict()


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return job.as_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    registry.cancel(job_id)
    return registry.get(job_id).as_dict()


# ---------------------------------------------------------------------------
# 時間割
# ---------------------------------------------------------------------------


@router.get("/timetables/{timetable_id}")
def get_timetable(timetable_id: int, db: Session = Depends(get_db)) -> dict:
    return _timetable_payload(db, _get_timetable(db, timetable_id))


@router.delete("/timetables/{timetable_id}", status_code=204)
def delete_timetable(timetable_id: int, db: Session = Depends(get_db)) -> Response:
    tt = _get_timetable(db, timetable_id)
    db.delete(tt)
    db.commit()
    return Response(status_code=204)


@router.post("/timetables/{timetable_id}/assignments", status_code=201)
def add_assignment(
    timetable_id: int, payload: AssignmentCreate, db: Session = Depends(get_db)
) -> dict:
    tt = _get_timetable(db, timetable_id)
    course = db.get(m.Course, payload.course_id)
    if course is None or course.school_id != tt.school_id:
        raise HTTPException(status_code=404, detail="講座が見つかりません")
    if any(
        x.course_id == payload.course_id
        and x.day == payload.day
        and x.period == payload.period
        for x in tt.assignments
    ):
        raise HTTPException(
            status_code=409, detail="同じ講座がすでにそのコマに配置されています"
        )
    db.add(
        m.Assignment(
            timetable_id=tt.id,
            course_id=payload.course_id,
            day=payload.day,
            period=payload.period,
        )
    )
    db.commit()
    db.refresh(tt)
    return _timetable_payload(db, tt)


@router.patch("/timetables/{timetable_id}/assignments/{assignment_id}")
def move_assignment(
    timetable_id: int,
    assignment_id: int,
    payload: AssignmentMove,
    db: Session = Depends(get_db),
) -> dict:
    tt = _get_timetable(db, timetable_id)
    a = db.get(m.Assignment, assignment_id)
    if a is None or a.timetable_id != tt.id:
        raise HTTPException(status_code=404, detail="割当が見つかりません")
    if a.locked:
        raise HTTPException(status_code=409, detail="固定された割当は動かせません")
    duplicate = [
        other
        for other in tt.assignments
        if other.id != a.id
        and other.course_id == a.course_id
        and other.day == payload.day
        and other.period == payload.period
    ]
    if duplicate:
        raise HTTPException(
            status_code=409, detail="同じ講座がすでにそのコマに配置されています"
        )
    a.day = payload.day
    a.period = payload.period
    db.commit()
    db.refresh(tt)
    return _timetable_payload(db, tt)


@router.delete("/timetables/{timetable_id}/assignments/{assignment_id}")
def delete_assignment(
    timetable_id: int, assignment_id: int, db: Session = Depends(get_db)
) -> dict:
    tt = _get_timetable(db, timetable_id)
    a = db.get(m.Assignment, assignment_id)
    if a is None or a.timetable_id != tt.id:
        raise HTTPException(status_code=404, detail="割当が見つかりません")
    if a.locked:
        raise HTTPException(status_code=409, detail="固定された割当は削除できません")
    db.delete(a)
    db.commit()
    db.refresh(tt)
    return _timetable_payload(db, tt)


@router.post("/timetables/{timetable_id}/assignments/{assignment_id}/lock")
def set_lock(
    timetable_id: int,
    assignment_id: int,
    payload: LockUpdate,
    db: Session = Depends(get_db),
) -> dict:
    tt = _get_timetable(db, timetable_id)
    a = db.get(m.Assignment, assignment_id)
    if a is None or a.timetable_id != tt.id:
        raise HTTPException(status_code=404, detail="割当が見つかりません")
    a.locked = payload.locked
    db.commit()
    db.refresh(tt)
    return _timetable_payload(db, tt)


@router.put("/timetables/{timetable_id}/assignments")
def replace_assignments(
    timetable_id: int, payload: AssignmentsReplace, db: Session = Depends(get_db)
) -> dict:
    """割当をまとめて置き換える。フロントの undo/redo はこれを使う。"""
    tt = _get_timetable(db, timetable_id)
    valid_course_ids = {
        c.id for c in db.query(m.Course).filter(m.Course.school_id == tt.school_id).all()
    }
    for item in payload.assignments:
        if item.course_id not in valid_course_ids:
            raise HTTPException(
                status_code=400, detail=f"講座 {item.course_id} はこの学校のものではありません"
            )
    for a in list(tt.assignments):
        db.delete(a)
    db.flush()
    for item in payload.assignments:
        db.add(
            m.Assignment(
                timetable_id=tt.id,
                course_id=item.course_id,
                day=item.day,
                period=item.period,
                locked=item.locked,
            )
        )
    db.commit()
    db.refresh(tt)
    return _timetable_payload(db, tt)


@router.post("/timetables/{timetable_id}/validate")
def validate_timetable(timetable_id: int, db: Session = Depends(get_db)) -> dict:
    tt = _get_timetable(db, timetable_id)
    payload = _timetable_payload(db, tt)
    return {"violations": payload["violations"], "summary": payload["summary"]}


@router.get("/timetables/{timetable_id}/export.csv")
def export_csv(
    timetable_id: int, by: str = "class", db: Session = Depends(get_db)
) -> Response:
    """時間割をCSVで出力する。by=class でクラス別、by=teacher で教員別。"""
    tt = _get_timetable(db, timetable_id)
    payload = _timetable_payload(db, tt)
    school = payload["school"]
    courses = {c["id"]: c for c in payload["courses"]}

    if by == "teacher":
        rows_meta = [(t["id"], t["name"]) for t in payload["teachers"]]

        def owns(course: dict, owner_id: int) -> bool:
            return course["teacher_id"] == owner_id
    else:
        rows_meta = [(k["id"], k["name"]) for k in payload["classes"]]

        def owns(course: dict, owner_id: int) -> bool:
            return owner_id in course["class_ids"]

    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["対象", "曜日"] + [f"{p + 1}限" for p in range(school["periods_per_day"])]
    writer.writerow(header)
    for owner_id, owner_name in rows_meta:
        cells: dict[tuple[int, int], list[str]] = {}
        for a in payload["assignments"]:
            course = courses[a["course_id"]]
            if owns(course, owner_id):
                label = course["short_name"]
                if by == "teacher":
                    label += "(" + "・".join(
                        k["name"]
                        for k in payload["classes"]
                        if k["id"] in course["class_ids"]
                    ) + ")"
                cells.setdefault((a["day"], a["period"]), []).append(label)
        if not cells:
            continue
        for d in range(school["days"]):
            row = [owner_name, school["day_names"][d]]
            for p in range(school["periods_per_day"]):
                row.append("/".join(sorted(cells.get((d, p), []))))
            writer.writerow(row)

    filename = f"timetable_{tt.id}_{by}.csv"
    return Response(
        # Excel で開いたときに文字化けしないよう BOM を付ける
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
