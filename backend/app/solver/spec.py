"""求解と検証が共有する問題定義。

ソルバーと検証エンジンが別々に制約を解釈すると、「画面上はOKなのに再提案で弾かれる」
というズレが起きる。それを防ぐため、制約は constraints.py に1回だけ定義し、
LP への追加（apply）と既存割当の検査（check）の両方を同じクラスが持つ。
このモジュールはその共通の入力型を定義する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

Severity = Literal["hard", "soft"]


@dataclass(frozen=True)
class Placement:
    """1つの割当（この講座を、この曜日・このコマに置く）。"""

    course_id: int
    day: int
    period: int

    @property
    def slot(self) -> tuple[int, int]:
        return (self.day, self.period)


@dataclass(frozen=True)
class TeacherSpec:
    id: int
    name: str
    max_weekly_periods: int
    # 不在枠 (day, period)
    unavailable: frozenset[tuple[int, int]] = frozenset()


@dataclass(frozen=True)
class CourseSpec:
    id: int
    label: str
    subject_id: int
    subject_name: str
    is_core: bool
    room_type: str | None
    teacher_id: int
    class_ids: tuple[int, ...]
    weekly_periods: int
    max_per_day: int = 1
    prefers_double: bool = False


@dataclass(frozen=True)
class ParallelGroupSpec:
    id: int
    name: str
    course_ids: tuple[int, ...]


@dataclass
class ProblemSpec:
    days: int
    periods_per_day: int
    courses: dict[int, CourseSpec] = field(default_factory=dict)
    teachers: dict[int, TeacherSpec] = field(default_factory=dict)
    class_names: dict[int, str] = field(default_factory=dict)
    # 特別教室の種別ごとの保有数。同一コマにこの数を超えて使えない
    room_capacity: dict[str, int] = field(default_factory=dict)
    # 配置禁止枠 (class_id, day, period)。class_id が None なら全学級
    blocked: frozenset[tuple[int | None, int, int]] = frozenset()
    parallel_groups: tuple[ParallelGroupSpec, ...] = ()
    # 固定された割当。再提案時に動かさない
    locked: frozenset[Placement] = frozenset()

    # ---- 導出プロパティ ----

    @property
    def slots(self) -> list[tuple[int, int]]:
        return [(d, p) for d in range(self.days) for p in range(self.periods_per_day)]

    @property
    def group_of_course(self) -> dict[int, int]:
        """講座 -> 所属する同時展開群。1講座は高々1群に属する（仮定 A-15）。"""
        out: dict[int, int] = {}
        for g in self.parallel_groups:
            for cid in g.course_ids:
                out.setdefault(cid, g.id)
        return out

    def groups_of_class(self, class_id: int) -> list[ParallelGroupSpec]:
        """その学級の講座を1つ以上含む同時展開群。"""
        return [
            g
            for g in self.parallel_groups
            if any(
                class_id in self.courses[cid].class_ids
                for cid in g.course_ids
                if cid in self.courses
            )
        ]

    def courses_of_teacher(self, teacher_id: int) -> list[CourseSpec]:
        return [c for c in self.courses.values() if c.teacher_id == teacher_id]

    def courses_of_class(self, class_id: int) -> list[CourseSpec]:
        return [c for c in self.courses.values() if class_id in c.class_ids]

    def is_blocked(self, class_id: int, day: int, period: int) -> bool:
        return (class_id, day, period) in self.blocked or (None, day, period) in self.blocked

    def course_blocked(self, course: CourseSpec, day: int, period: int) -> bool:
        """講座が置けない枠か。受講学級のいずれかが禁止枠なら置けない（ハード制約 H4）。"""
        if any(self.is_blocked(cid, day, period) for cid in course.class_ids):
            return True
        teacher = self.teachers.get(course.teacher_id)
        # 教員の不在枠（ハード制約 H5）
        if teacher and (day, period) in teacher.unavailable:
            return True
        return False

    def allowed_slots(self, course: CourseSpec) -> list[tuple[int, int]]:
        return [s for s in self.slots if not self.course_blocked(course, *s)]


@dataclass(frozen=True)
class Violation:
    """制約違反。検証エンジンとソルバーの両方が同じ型で違反を返す。"""

    code: str
    severity: Severity
    message: str
    course_ids: tuple[int, ...] = ()
    class_ids: tuple[int, ...] = ()
    teacher_ids: tuple[int, ...] = ()
    slots: tuple[tuple[int, int], ...] = ()

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "course_ids": list(self.course_ids),
            "class_ids": list(self.class_ids),
            "teacher_ids": list(self.teacher_ids),
            "slots": [{"day": d, "period": p} for d, p in self.slots],
        }


def group_by_slot(placements: Iterable[Placement]) -> dict[tuple[int, int], list[Placement]]:
    out: dict[tuple[int, int], list[Placement]] = {}
    for pl in placements:
        out.setdefault(pl.slot, []).append(pl)
    return out
