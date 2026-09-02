"""ソルバーと検証エンジンのテスト。

同じ制約定義が「LPへの追加」と「既存割当の検査」の両方で使われていることを、
両者の結果が食い違わないことで確かめる。
"""

from __future__ import annotations

import pytest

from app.solver.engine import LockConflictError, solve, validate
from app.solver.spec import (
    CourseSpec,
    ParallelGroupSpec,
    Placement,
    ProblemSpec,
    TeacherSpec,
)


def make_course(cid: int, label: str, teacher_id: int, class_ids, periods: int, **kw) -> CourseSpec:
    return CourseSpec(
        id=cid,
        label=label,
        subject_id=cid,
        subject_name=label,
        is_core=kw.pop("is_core", False),
        room_type=kw.pop("room_type", None),
        teacher_id=teacher_id,
        class_ids=tuple(class_ids),
        weekly_periods=periods,
        max_per_day=kw.pop("max_per_day", 1),
        prefers_double=kw.pop("prefers_double", False),
    )


def simple_spec(**overrides) -> ProblemSpec:
    spec = ProblemSpec(
        days=5,
        periods_per_day=6,
        class_names={1: "1年1組", 2: "1年2組"},
        teachers={
            1: TeacherSpec(1, "国語 教諭1", 18),
            2: TeacherSpec(2, "数学 教諭1", 18),
        },
        courses={
            1: make_course(1, "1年1組 国語", 1, [1], 4),
            2: make_course(2, "1年1組 数学", 2, [1], 4),
            3: make_course(3, "1年2組 国語", 1, [2], 4),
            4: make_course(4, "1年2組 数学", 2, [2], 4),
        },
    )
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


def test_solve_fills_all_periods_when_feasible() -> None:
    result = solve(simple_spec(), time_limit_sec=20)
    assert result.unmet_periods == 0
    assert result.total_periods == 16
    assert [v for v in result.violations if v.severity == "hard"] == []


def test_solve_never_returns_infeasible_even_when_over_constrained() -> None:
    """枠が足りなくても解は返り、不足はS1の未充足コマ数として定量化される。"""
    spec = simple_spec()
    # 週30枠しかないところに1学級で40コマ要求する
    spec.courses[1] = make_course(1, "1年1組 国語", 1, [1], 40, max_per_day=6)
    result = solve(spec, time_limit_sec=20)

    assert result.status != "Infeasible"
    assert result.unmet_periods > 0
    assert any(v.code == "S1" for v in result.violations)


def test_teacher_conflict_is_never_produced() -> None:
    """同じ教員が2学級を担当していても、同時刻に重ならない。"""
    spec = simple_spec()
    result = solve(spec, time_limit_sec=20)
    by_slot: dict[tuple[int, int, int], int] = {}
    for pl in result.placements:
        key = (spec.courses[pl.course_id].teacher_id, pl.day, pl.period)
        by_slot[key] = by_slot.get(key, 0) + 1
    assert max(by_slot.values()) == 1


def test_blocked_slots_are_respected() -> None:
    spec = simple_spec()
    spec.blocked = frozenset((None, 4, p) for p in range(6))  # 金曜終日を禁止
    result = solve(spec, time_limit_sec=20)
    assert all(pl.day != 4 for pl in result.placements)
    assert result.unmet_periods == 0


def test_teacher_unavailability_is_respected() -> None:
    spec = simple_spec()
    spec.teachers[1] = TeacherSpec(1, "国語 教諭1", 18, frozenset({(0, 0), (0, 1)}))
    result = solve(spec, time_limit_sec=20)
    kokugo = {1, 3}
    assert all(
        not (pl.course_id in kokugo and (pl.day, pl.period) in {(0, 0), (0, 1)})
        for pl in result.placements
    )


def test_room_capacity_limits_concurrent_use() -> None:
    spec = simple_spec()
    spec.room_capacity = {"理科室": 1}
    spec.courses[5] = make_course(5, "1年1組 理科", 1, [1], 3, room_type="理科室")
    spec.courses[6] = make_course(6, "1年2組 理科", 2, [2], 3, room_type="理科室")
    result = solve(spec, time_limit_sec=20)
    used: dict[tuple[int, int], int] = {}
    for pl in result.placements:
        if spec.courses[pl.course_id].room_type == "理科室":
            used[(pl.day, pl.period)] = used.get((pl.day, pl.period), 0) + 1
    assert not used or max(used.values()) <= 1


def test_locked_assignments_are_kept() -> None:
    spec = simple_spec()
    spec.locked = frozenset({Placement(1, 0, 0), Placement(2, 1, 2)})
    result = solve(spec, time_limit_sec=20)
    assert Placement(1, 0, 0) in result.placements
    assert Placement(2, 1, 2) in result.placements


def test_conflicting_locks_raise_with_reasons() -> None:
    """固定同士が矛盾していたら、理由付きで拒否する（黙って解を返さない）。"""
    spec = simple_spec()
    # 同じ学級の同じコマに2講座を固定する
    spec.locked = frozenset({Placement(1, 0, 0), Placement(2, 0, 0)})
    with pytest.raises(LockConflictError) as excinfo:
        solve(spec, time_limit_sec=20)
    codes = {v.code for v in excinfo.value.violations}
    assert "H1" in codes


def test_parallel_group_members_share_slots() -> None:
    """高校の選択科目: 群の講座は同一コマに並ぶ。"""
    spec = ProblemSpec(
        days=5,
        periods_per_day=6,
        class_names={1: "2年1組"},
        teachers={
            1: TeacherSpec(1, "物理 教諭", 18),
            2: TeacherSpec(2, "化学 教諭", 18),
            3: TeacherSpec(3, "生物 教諭", 18),
            4: TeacherSpec(4, "国語 教諭", 18),
        },
        courses={
            1: make_course(1, "2年1組 物理基礎", 1, [1], 3),
            2: make_course(2, "2年1組 化学基礎", 2, [1], 3),
            3: make_course(3, "2年1組 生物基礎", 3, [1], 3),
            4: make_course(4, "2年1組 論理国語", 4, [1], 4),
        },
        parallel_groups=(ParallelGroupSpec(1, "2年 理科選択", (1, 2, 3)),),
    )
    result = solve(spec, time_limit_sec=20)
    slots = {cid: set() for cid in (1, 2, 3)}
    for pl in result.placements:
        if pl.course_id in slots:
            slots[pl.course_id].add(pl.slot)
    assert slots[1] == slots[2] == slots[3]
    assert len(slots[1]) == 3
    # 選択科目は学級から見れば1コマなので、国語4コマと合わせて週7コマ埋まる
    assert result.unmet_periods == 0


def test_parallel_group_does_not_trigger_class_conflict() -> None:
    """同一学級に並列開講しても H1（学級の重複）にはならない。"""
    spec = ProblemSpec(
        days=5,
        periods_per_day=6,
        class_names={1: "2年1組"},
        teachers={1: TeacherSpec(1, "物理", 18), 2: TeacherSpec(2, "化学", 18)},
        courses={
            1: make_course(1, "2年1組 物理基礎", 1, [1], 2),
            2: make_course(2, "2年1組 化学基礎", 2, [1], 2),
        },
        parallel_groups=(ParallelGroupSpec(1, "理科選択", (1, 2)),),
    )
    placements = [Placement(1, 0, 0), Placement(2, 0, 0), Placement(1, 1, 0), Placement(2, 1, 0)]
    violations = validate(spec, placements)
    assert [v for v in violations if v.code == "H1"] == []


def test_validate_detects_manual_class_conflict() -> None:
    spec = simple_spec()
    violations = validate(spec, [Placement(1, 0, 0), Placement(2, 0, 0)])
    hard = [v for v in violations if v.severity == "hard"]
    assert any(v.code == "H1" for v in hard)
    assert "1年1組" in hard[0].message


def test_validate_detects_teacher_conflict() -> None:
    spec = simple_spec()
    # 講座1と3は同じ国語教諭
    violations = validate(spec, [Placement(1, 0, 0), Placement(3, 0, 0)])
    assert any(v.code == "H2" for v in violations)


def test_validate_detects_teacher_overload() -> None:
    spec = simple_spec()
    spec.teachers[1] = TeacherSpec(1, "国語 教諭1", 2)
    placements = [Placement(1, 0, p) for p in range(4)]
    violations = validate(spec, placements)
    assert any(v.code == "S3" for v in violations)


def test_validate_detects_blocked_slot_after_manual_move() -> None:
    spec = simple_spec()
    spec.blocked = frozenset({(1, 0, 0)})
    violations = validate(spec, [Placement(1, 0, 0)])
    assert any(v.code == "H4" for v in violations)


def test_solver_output_passes_its_own_validator() -> None:
    """求解結果を検証エンジンにかけてもハード違反が出ない（両者の定義が一致している）。"""
    spec = simple_spec()
    spec.courses[5] = make_course(5, "1年1組 理科", 1, [1], 3, room_type="理科室", prefers_double=True, max_per_day=2)
    spec.room_capacity = {"理科室": 1}
    result = solve(spec, time_limit_sec=20)
    revalidated = validate(spec, result.placements)
    assert [v.code for v in revalidated if v.severity == "hard"] == []
    assert [v.code for v in result.violations if v.severity == "hard"] == []


def test_same_course_twice_in_one_slot_is_a_conflict() -> None:
    """同じ講座を同じコマに2つ置くのは、たとえ同時展開群でも二重予約。"""
    spec = simple_spec()
    violations = validate(spec, [Placement(1, 0, 0), Placement(1, 0, 0)])
    assert any(v.code == "H1" for v in violations)

    grouped = ProblemSpec(
        days=5,
        periods_per_day=6,
        class_names={1: "2年1組"},
        teachers={1: TeacherSpec(1, "物理", 18), 2: TeacherSpec(2, "化学", 18)},
        courses={
            1: make_course(1, "2年1組 物理基礎", 1, [1], 2),
            2: make_course(2, "2年1組 化学基礎", 2, [1], 2),
        },
        parallel_groups=(ParallelGroupSpec(1, "理科選択", (1, 2)),),
    )
    assert any(
        v.code == "H1" for v in validate(grouped, [Placement(1, 0, 0), Placement(1, 0, 0)])
    )
