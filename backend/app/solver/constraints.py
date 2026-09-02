"""制約の単一情報源。

各制約クラスが2つの顔を持つ:

- ``apply(spec, ctx)``  … 整数計画モデルに制約と目的関数項を追加する（自動提案で使う）
- ``check(spec, placements)`` … 既存の割当を検査して違反を返す（手編集の即時検証で使う）

両者を同じクラスに置くことで、「画面上はOKなのに再提案すると弾かれる」というズレが
構造的に起きないようにしている（要件書 2-2）。

ハード制約は「すべての講座を1つも配置しない解」で必ず充足できる形にしてある。
したがってモデルは常に実行可能であり、「解が返らない」状態は起こらない。
不足はソフト制約 S1 の未充足コマ数として必ず定量化される（仮定 A-13）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import pulp

from .spec import (
    CourseSpec,
    Placement,
    ProblemSpec,
    Severity,
    Violation,
)

DAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"]


def slot_label(day: int, period: int) -> str:
    return f"{DAY_NAMES[day % 7]}{period + 1}限"


@dataclass
class LpContext:
    """LP モデル組み立て用の作業領域。"""

    problem: pulp.LpProblem
    # (course_id, day, period) -> 0/1 変数。配置禁止枠には変数を作らない（H4/H5 の表現）
    x: dict[tuple[int, int, int], pulp.LpVariable]
    # (group_id, day, period) -> 0/1 変数。同時展開群がそのコマを使うか。
    # H1（学級の重複）と S4（同時展開）が共有する。選択科目は学級から見れば
    # 1つのセルなので、H1 は群を1つ分としてしか数えてはいけない。
    z: dict[tuple[int, int, int], pulp.LpVariable] = field(default_factory=dict)
    objective_terms: list = field(default_factory=list)

    def var(self, course_id: int, day: int, period: int):
        return self.x.get((course_id, day, period))

    def group_var(self, group_id: int, day: int, period: int):
        return self.z.get((group_id, day, period))

    def penalty(self, name: str, weight: float, up_bound: float | None = None):
        v = pulp.LpVariable(name, lowBound=0, upBound=up_bound)
        self.objective_terms.append(weight * v)
        return v

    def reward(self, name: str, weight: float):
        # 目的関数で最大化する向きに入るため、x が二値なら連続変数でも
        # 最適解では min(x_a, x_b) に一致する。二値にすると探索が重くなるだけ
        v = pulp.LpVariable(name, lowBound=0, upBound=1)
        self.objective_terms.append(-weight * v)
        return v

    def vars_for(
        self, course_ids: Sequence[int], slots: Sequence[tuple[int, int]]
    ) -> list:
        return [
            self.x[(cid, d, p)]
            for cid in course_ids
            for (d, p) in slots
            if (cid, d, p) in self.x
        ]


class Constraint:
    code: str = ""
    label: str = ""
    severity: Severity = "hard"
    weight: float = 0.0

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:  # pragma: no cover - 抽象
        raise NotImplementedError

    def check(
        self, spec: ProblemSpec, placements: Sequence[Placement]
    ) -> list[Violation]:  # pragma: no cover - 抽象
        raise NotImplementedError


# --------------------------------------------------------------------------
# ハード制約
# --------------------------------------------------------------------------


class ClassOccupancy(Constraint):
    """H1: 1つの学級の同一コマに2つ以上の講座を置かない。"""

    code = "H1"
    label = "学級の重複"
    severity = "hard"

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        grouped = spec.group_of_course
        for class_id in spec.class_names:
            # 同時展開群に属する講座は、学級から見ると1つのセル（選択の時間）なので
            # 個々の講座ではなく群インジケータで数える
            solo_ids = [
                c.id for c in spec.courses_of_class(class_id) if c.id not in grouped
            ]
            groups = spec.groups_of_class(class_id)
            if not solo_ids and not groups:
                continue
            for d, p in spec.slots:
                cell = ctx.vars_for(solo_ids, [(d, p)])
                cell += [
                    ctx.group_var(g.id, d, p)
                    for g in groups
                    if ctx.group_var(g.id, d, p) is not None
                ]
                if len(cell) > 1:
                    ctx.problem += pulp.lpSum(cell) <= 1, f"H1_c{class_id}_{d}_{p}"

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        grouped = spec.group_of_course
        seen: dict[tuple[int, int, int], list[Placement]] = {}
        for pl in placements:
            course = spec.courses.get(pl.course_id)
            if not course:
                continue
            for cid in course.class_ids:
                seen.setdefault((cid, pl.day, pl.period), []).append(pl)
        out = []
        for (cid, d, p), pls in sorted(seen.items()):
            if len(pls) <= 1:
                continue
            # 学級の1コマを正当に占められるのは次のどちらか:
            #   * 単独の講座が1つ
            #   * 同一の同時展開群に属する、互いに異なる講座（選択科目の並列開講）
            # 同じ講座が同じコマに2つあるのは、群であっても二重予約なので違反
            units = {grouped.get(x.course_id, ("solo", x.course_id)) for x in pls}
            duplicated_course = len({x.course_id for x in pls}) < len(pls)
            if len(units) > 1 or duplicated_course:
                names = "、".join(spec.courses[x.course_id].label for x in pls)
                out.append(
                    Violation(
                        code=self.code,
                        severity="hard",
                        message=f"{spec.class_names[cid]} の{slot_label(d, p)}に {names} が重複しています",
                        course_ids=tuple(x.course_id for x in pls),
                        class_ids=(cid,),
                        slots=((d, p),),
                    )
                )
        return out


class TeacherOccupancy(Constraint):
    """H2: 1人の教員が同一コマに2つ以上の講座を担当しない。"""

    code = "H2"
    label = "教員の重複"
    severity = "hard"

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        for teacher_id in spec.teachers:
            course_ids = [c.id for c in spec.courses_of_teacher(teacher_id)]
            if len(course_ids) < 2:
                continue
            for d, p in spec.slots:
                cell = ctx.vars_for(course_ids, [(d, p)])
                if len(cell) > 1:
                    ctx.problem += pulp.lpSum(cell) <= 1, f"H2_t{teacher_id}_{d}_{p}"

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        seen: dict[tuple[int, int, int], list[Placement]] = {}
        for pl in placements:
            course = spec.courses.get(pl.course_id)
            if not course:
                continue
            seen.setdefault((course.teacher_id, pl.day, pl.period), []).append(pl)
        out = []
        for (tid, d, p), pls in sorted(seen.items()):
            if len(pls) > 1:
                names = "、".join(spec.courses[x.course_id].label for x in pls)
                out.append(
                    Violation(
                        code=self.code,
                        severity="hard",
                        message=(
                            f"{spec.teachers[tid].name} が{slot_label(d, p)}に "
                            f"{names} を同時に担当しています"
                        ),
                        course_ids=tuple(x.course_id for x in pls),
                        teacher_ids=(tid,),
                        slots=((d, p),),
                    )
                )
        return out


class RoomCapacity(Constraint):
    """H3: 特別教室の同時使用数が保有数を超えない。"""

    code = "H3"
    label = "特別教室の不足"
    severity = "hard"

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        for room_type, capacity in spec.room_capacity.items():
            course_ids = [c.id for c in spec.courses.values() if c.room_type == room_type]
            if not course_ids:
                continue
            for d, p in spec.slots:
                cell = ctx.vars_for(course_ids, [(d, p)])
                if len(cell) > capacity:
                    ctx.problem += pulp.lpSum(cell) <= capacity, f"H3_{room_type}_{d}_{p}"

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        seen: dict[tuple[str, int, int], list[Placement]] = {}
        for pl in placements:
            course = spec.courses.get(pl.course_id)
            if not course or not course.room_type:
                continue
            seen.setdefault((course.room_type, pl.day, pl.period), []).append(pl)
        out = []
        for (room_type, d, p), pls in sorted(seen.items()):
            capacity = spec.room_capacity.get(room_type, 0)
            if len(pls) > capacity:
                out.append(
                    Violation(
                        code=self.code,
                        severity="hard",
                        message=(
                            f"{slot_label(d, p)}に {room_type} を {len(pls)} 講座が使用しますが "
                            f"{capacity} 室しかありません"
                        ),
                        course_ids=tuple(x.course_id for x in pls),
                        slots=((d, p),),
                    )
                )
        return out


class BlockedSlotConstraint(Constraint):
    """H4/H5: 配置禁止枠と教員の不在枠には置かない。

    LP では該当する (講座, コマ) の変数自体を作らないことで表現しているため、
    apply では何もしない。手編集では置けてしまうので check で検出する。
    """

    code = "H4"
    label = "配置禁止枠"
    severity = "hard"

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        return None

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        out = []
        for pl in placements:
            course = spec.courses.get(pl.course_id)
            if not course:
                continue
            blocked_classes = [
                cid for cid in course.class_ids if spec.is_blocked(cid, pl.day, pl.period)
            ]
            if blocked_classes:
                out.append(
                    Violation(
                        code="H4",
                        severity="hard",
                        message=f"{course.label} が配置禁止枠（{slot_label(pl.day, pl.period)}）に置かれています",
                        course_ids=(course.id,),
                        class_ids=tuple(blocked_classes),
                        slots=((pl.day, pl.period),),
                    )
                )
            teacher = spec.teachers.get(course.teacher_id)
            if teacher and (pl.day, pl.period) in teacher.unavailable:
                out.append(
                    Violation(
                        code="H5",
                        severity="hard",
                        message=(
                            f"{teacher.name} は{slot_label(pl.day, pl.period)}が不在ですが "
                            f"{course.label} が割り当てられています"
                        ),
                        course_ids=(course.id,),
                        teacher_ids=(teacher.id,),
                        slots=((pl.day, pl.period),),
                    )
                )
        return out


class LockedAssignment(Constraint):
    """H6: 固定された割当は動かさない。"""

    code = "H6"
    label = "固定された割当"
    severity = "hard"

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        for pl in sorted(spec.locked, key=lambda p: (p.course_id, p.day, p.period)):
            var = ctx.var(pl.course_id, pl.day, pl.period)
            if var is not None:
                ctx.problem += var == 1, f"H6_{pl.course_id}_{pl.day}_{pl.period}"

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        present = set(placements)
        out = []
        for pl in sorted(spec.locked, key=lambda p: (p.course_id, p.day, p.period)):
            if pl not in present:
                course = spec.courses.get(pl.course_id)
                label = course.label if course else f"講座{pl.course_id}"
                out.append(
                    Violation(
                        code=self.code,
                        severity="hard",
                        message=f"固定された {label}（{slot_label(pl.day, pl.period)}）が外れています",
                        course_ids=(pl.course_id,),
                        slots=((pl.day, pl.period),),
                    )
                )
        return out


# --------------------------------------------------------------------------
# ソフト制約
# --------------------------------------------------------------------------


class WeeklyPeriods(Constraint):
    """S1: 講座の週コマ数を満たす。最優先のソフト制約。"""

    code = "S1"
    label = "週コマ数の未充足"
    severity = "soft"
    weight = 1000.0

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        for course in spec.courses.values():
            cell = ctx.vars_for([course.id], spec.allowed_slots(course))
            if not cell:
                continue
            expr = pulp.lpSum(cell)
            short = ctx.penalty(f"S1_short_{course.id}", self.weight, up_bound=course.weekly_periods)
            ctx.problem += expr + short >= course.weekly_periods, f"S1_min_{course.id}"
            # 超過は許さない（空解で充足可能なのでハードにしても実行可能性を損なわない）
            ctx.problem += expr <= course.weekly_periods, f"S1_max_{course.id}"

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        counts: dict[int, int] = {}
        for pl in placements:
            counts[pl.course_id] = counts.get(pl.course_id, 0) + 1
        out = []
        for course in sorted(spec.courses.values(), key=lambda c: c.id):
            n = counts.get(course.id, 0)
            if n < course.weekly_periods:
                out.append(
                    Violation(
                        code=self.code,
                        severity="soft",
                        message=(
                            f"{course.label} は週{course.weekly_periods}コマ必要ですが "
                            f"{n}コマしか配置されていません"
                        ),
                        course_ids=(course.id,),
                        class_ids=course.class_ids,
                    )
                )
            elif n > course.weekly_periods:
                out.append(
                    Violation(
                        code=self.code,
                        severity="soft",
                        message=(
                            f"{course.label} は週{course.weekly_periods}コマですが "
                            f"{n}コマ配置されています"
                        ),
                        course_ids=(course.id,),
                        class_ids=course.class_ids,
                    )
                )
        return out


class MaxPerDay(Constraint):
    """S2: 同じ講座を1日に置ける回数の上限。週コマ数の週内分散（S6）も兼ねる。"""

    code = "S2"
    label = "同一教科の1日重複"
    severity = "soft"
    weight = 100.0

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        for course in spec.courses.values():
            for d in range(spec.days):
                slots = [(d, p) for p in range(spec.periods_per_day)]
                cell = ctx.vars_for([course.id], slots)
                if len(cell) <= course.max_per_day:
                    continue
                over = ctx.penalty(f"S2_over_{course.id}_{d}", self.weight)
                ctx.problem += (
                    pulp.lpSum(cell) - over <= course.max_per_day,
                    f"S2_{course.id}_{d}",
                )

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        counts: dict[tuple[int, int], int] = {}
        for pl in placements:
            counts[(pl.course_id, pl.day)] = counts.get((pl.course_id, pl.day), 0) + 1
        out = []
        for (course_id, day), n in sorted(counts.items()):
            course = spec.courses.get(course_id)
            if course and n > course.max_per_day:
                out.append(
                    Violation(
                        code=self.code,
                        severity="soft",
                        message=(
                            f"{course.label} が{DAY_NAMES[day % 7]}曜に{n}コマあります"
                            f"（上限{course.max_per_day}コマ）"
                        ),
                        course_ids=(course_id,),
                        class_ids=course.class_ids,
                        slots=((day, 0),),
                    )
                )
        return out


class TeacherWeeklyLoad(Constraint):
    """S3: 教員の週持ちコマ数の上限。既定18コマは教員勤務実態調査の平均に基づく。"""

    code = "S3"
    label = "教員の持ちコマ超過"
    severity = "soft"
    weight = 50.0

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        for teacher in spec.teachers.values():
            course_ids = [c.id for c in spec.courses_of_teacher(teacher.id)]
            cell = ctx.vars_for(course_ids, spec.slots)
            if not cell:
                continue
            over = ctx.penalty(f"S3_over_{teacher.id}", self.weight)
            ctx.problem += (
                pulp.lpSum(cell) - over <= teacher.max_weekly_periods,
                f"S3_{teacher.id}",
            )

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        load: dict[int, int] = {}
        for pl in placements:
            course = spec.courses.get(pl.course_id)
            if course:
                load[course.teacher_id] = load.get(course.teacher_id, 0) + 1
        out = []
        for teacher_id, n in sorted(load.items()):
            teacher = spec.teachers[teacher_id]
            if n > teacher.max_weekly_periods:
                out.append(
                    Violation(
                        code=self.code,
                        severity="soft",
                        message=(
                            f"{teacher.name} の持ちコマが週{n}コマで、"
                            f"上限{teacher.max_weekly_periods}コマを超えています"
                        ),
                        teacher_ids=(teacher_id,),
                    )
                )
        return out


class ParallelGroupAlignment(Constraint):
    """S4/S5: 同時展開群の講座を同一コマに揃える。

    高校の選択科目の並列開講と、特別支援学級の交流及び共同学習の両方に使う。
    """

    code = "S4"
    label = "同時展開のずれ"
    severity = "soft"
    weight = 500.0

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        for group in spec.parallel_groups:
            member_ids = [cid for cid in group.course_ids if cid in spec.courses]
            if len(member_ids) < 2:
                continue
            for d, p in spec.slots:
                z = ctx.group_var(group.id, d, p)
                if z is None:
                    continue
                for cid in member_ids:
                    var = ctx.var(cid, d, p)
                    if var is None:
                        # 置けない枠なら、群としてもそのコマは使えない
                        ctx.problem += z == 0, f"S4_block_{group.id}_{cid}_{d}_{p}"
                        continue
                    # 等式にする。H1（学級の重複）は選択科目群を z で1セルとして
                    # 数えているため、ここを緩めると H1 が実質ソフト化してしまう。
                    # 空解（すべて0）で充足できるのでモデルは依然として常に実行可能。
                    ctx.problem += var == z, f"S4_eq_{group.id}_{cid}_{d}_{p}"

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        by_course: dict[int, set[tuple[int, int]]] = {}
        for pl in placements:
            by_course.setdefault(pl.course_id, set()).add(pl.slot)
        out = []
        for group in spec.parallel_groups:
            member_ids = [cid for cid in group.course_ids if cid in spec.courses]
            if len(member_ids) < 2:
                continue
            slot_sets = [by_course.get(cid, set()) for cid in member_ids]
            union = set().union(*slot_sets)
            intersection = set(union)
            for s in slot_sets:
                intersection &= s
            misaligned = sorted(union - intersection)
            if misaligned:
                out.append(
                    Violation(
                        code=self.code,
                        severity="soft",
                        message=(
                            f"同時展開群「{group.name}」の講座が"
                            f"{'、'.join(slot_label(d, p) for d, p in misaligned)} で揃っていません"
                        ),
                        course_ids=tuple(member_ids),
                        slots=tuple(misaligned),
                    )
                )
        return out


class DoublePeriod(Constraint):
    """S8: 実験・実習・体育などを2コマ連続で配置する。"""

    code = "S8"
    label = "2コマ連続の未確保"
    severity = "soft"
    weight = 20.0

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        for course in spec.courses.values():
            if not course.prefers_double or course.weekly_periods < 2:
                continue
            pairs = []
            for d in range(spec.days):
                for p in range(spec.periods_per_day - 1):
                    a = ctx.var(course.id, d, p)
                    b = ctx.var(course.id, d, p + 1)
                    if a is None or b is None:
                        continue
                    z = ctx.reward(f"S8_pair_{course.id}_{d}_{p}", self.weight)
                    ctx.problem += z <= a, f"S8_a_{course.id}_{d}_{p}"
                    ctx.problem += z <= b, f"S8_b_{course.id}_{d}_{p}"
                    pairs.append(z)
            if pairs:
                ctx.problem += (
                    pulp.lpSum(pairs) <= course.weekly_periods // 2,
                    f"S8_cap_{course.id}",
                )

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        by_course: dict[int, set[tuple[int, int]]] = {}
        for pl in placements:
            by_course.setdefault(pl.course_id, set()).add(pl.slot)
        out = []
        for course in sorted(spec.courses.values(), key=lambda c: c.id):
            if not course.prefers_double or course.weekly_periods < 2:
                continue
            slots = by_course.get(course.id, set())
            has_pair = any((d, p + 1) in slots for (d, p) in slots)
            if slots and not has_pair:
                out.append(
                    Violation(
                        code=self.code,
                        severity="soft",
                        message=f"{course.label} は2コマ連続が望ましいですが、連続していません",
                        course_ids=(course.id,),
                        class_ids=course.class_ids,
                    )
                )
        return out


class CoreSubjectsInMorning(Constraint):
    """S9: 主要教科を午前（1〜4限）に寄せる。5限以降への配置にペナルティを課す。"""

    code = "S9"
    label = "主要教科の午後配置"
    severity = "soft"
    weight = 5.0
    afternoon_from = 4  # 0-indexed。5限目以降を午後とみなす

    def _is_afternoon(self, spec: ProblemSpec, period: int) -> bool:
        return period >= min(self.afternoon_from, spec.periods_per_day - 1)

    def apply(self, spec: ProblemSpec, ctx: LpContext) -> None:
        terms = []
        for course in spec.courses.values():
            if not course.is_core:
                continue
            for d, p in spec.slots:
                if not self._is_afternoon(spec, p):
                    continue
                var = ctx.var(course.id, d, p)
                if var is not None:
                    terms.append(var)
        if terms:
            ctx.objective_terms.append(self.weight * pulp.lpSum(terms))

    def check(self, spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
        out = []
        for pl in sorted(placements, key=lambda p: (p.course_id, p.day, p.period)):
            course = spec.courses.get(pl.course_id)
            if course and course.is_core and self._is_afternoon(spec, pl.period):
                out.append(
                    Violation(
                        code=self.code,
                        severity="soft",
                        message=f"{course.label} が{slot_label(pl.day, pl.period)}（午後）に配置されています",
                        course_ids=(course.id,),
                        class_ids=course.class_ids,
                        slots=((pl.day, pl.period),),
                    )
                )
        return out


# 適用順は目的関数の重み順ではなく、違反リストの表示順を決める
ALL_CONSTRAINTS: tuple[Constraint, ...] = (
    ClassOccupancy(),
    TeacherOccupancy(),
    RoomCapacity(),
    BlockedSlotConstraint(),
    LockedAssignment(),
    WeeklyPeriods(),
    MaxPerDay(),
    TeacherWeeklyLoad(),
    ParallelGroupAlignment(),
    DoublePeriod(),
    CoreSubjectsInMorning(),
)

CONSTRAINT_INFO = [
    {"code": c.code, "label": c.label, "severity": c.severity, "weight": c.weight}
    for c in ALL_CONSTRAINTS
]


def course_label(course: CourseSpec, spec: ProblemSpec) -> str:
    return course.label
