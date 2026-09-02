"""求解エンジンと検証エンジン。

どちらも constraints.ALL_CONSTRAINTS を唯一の情報源として使う。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Sequence

import pulp

from .constraints import ALL_CONSTRAINTS, LpContext
from .spec import Placement, ProblemSpec, Violation

# 仮定 A-07: 求解の既定タイムアウト。品質は15秒で頭打ちになることを実測したため30秒
DEFAULT_TIME_LIMIT_SEC = 30
# 仮定 A-27: 最適性の証明に時間の大半が費やされるため、相対ギャップ2%で打ち切る。
# 実用上、2%以内の差は「体育が午後に1コマ寄る」程度の違いにしかならない
DEFAULT_GAP_REL = 0.02


class LockConflictError(Exception):
    """固定された割当同士が矛盾していて求解できない（仮定 A-11）。"""

    def __init__(self, violations: list[Violation]):
        self.violations = violations
        super().__init__("固定された割当に矛盾があります")


@dataclass
class SolveResult:
    placements: list[Placement]
    violations: list[Violation]
    status: str
    objective: float
    elapsed_sec: float
    unmet_periods: int
    total_periods: int
    # 時間制限に達して最適性が証明できなかった場合 True
    timed_out: bool = False
    stats: dict = field(default_factory=dict)

    @property
    def filled_periods(self) -> int:
        return self.total_periods - self.unmet_periods


def validate(spec: ProblemSpec, placements: Sequence[Placement]) -> list[Violation]:
    """割当を全制約で検査し、違反を返す。ハード違反を先に並べる。"""
    violations: list[Violation] = []
    for constraint in ALL_CONSTRAINTS:
        violations.extend(constraint.check(spec, placements))
    violations.sort(key=lambda v: (0 if v.severity == "hard" else 1, v.code))
    return violations


def check_locks(spec: ProblemSpec) -> list[Violation]:
    """固定された割当だけを取り出してハード違反がないか調べる。"""
    locked = sorted(spec.locked, key=lambda p: (p.day, p.period, p.course_id))
    if not locked:
        return []
    # H6 は「固定が外れていないか」の検査なので、ここでは対象外にする
    violations: list[Violation] = []
    for constraint in ALL_CONSTRAINTS:
        if constraint.code == "H6":
            continue
        violations.extend(
            v for v in constraint.check(spec, locked) if v.severity == "hard"
        )
    return violations


def build_model(spec: ProblemSpec) -> tuple[pulp.LpProblem, LpContext]:
    problem = pulp.LpProblem("timetable", pulp.LpMinimize)
    x: dict[tuple[int, int, int], pulp.LpVariable] = {}
    for course in spec.courses.values():
        # 配置禁止枠・教員不在枠には変数を作らない（ハード制約 H4/H5 の表現）
        for d, p in spec.allowed_slots(course):
            x[(course.id, d, p)] = pulp.LpVariable(
                f"x_{course.id}_{d}_{p}", cat=pulp.LpBinary
            )
    # 同時展開群のインジケータ。H1 と S4 が共有するため、制約適用の前に作る
    z: dict[tuple[int, int, int], pulp.LpVariable] = {}
    for group in spec.parallel_groups:
        if len([cid for cid in group.course_ids if cid in spec.courses]) < 2:
            continue
        for d, p in spec.slots:
            z[(group.id, d, p)] = pulp.LpVariable(
                f"z_{group.id}_{d}_{p}", cat=pulp.LpBinary
            )
    ctx = LpContext(problem=problem, x=x, z=z)
    for constraint in ALL_CONSTRAINTS:
        constraint.apply(spec, ctx)
    problem += pulp.lpSum(ctx.objective_terms) if ctx.objective_terms else 0
    return problem, ctx


def solve(
    spec: ProblemSpec,
    time_limit_sec: int = DEFAULT_TIME_LIMIT_SEC,
    gap_rel: float = DEFAULT_GAP_REL,
    msg: bool = False,
) -> SolveResult:
    """時間割を自動提案する。

    モデルは常に実行可能なので「解なし」は返らない。時間制限に達した場合は
    その時点の最良解を返し、``timed_out`` を True にする。
    """
    lock_violations = check_locks(spec)
    if lock_violations:
        raise LockConflictError(lock_violations)

    problem, ctx = build_model(spec)
    started = time.time()
    status_code = problem.solve(
        pulp.PULP_CBC_CMD(msg=msg, timeLimit=time_limit_sec, gapRel=gap_rel)
    )
    elapsed = time.time() - started
    status = pulp.LpStatus[status_code]
    # CBC は時間制限で打ち切っても LpStatus は Optimal を返すことがある。
    # 最適性が証明されたかどうかは sol_status で判定する
    proven_optimal = problem.sol_status == pulp.LpSolutionOptimal

    placements = [
        Placement(course_id=cid, day=d, period=p)
        for (cid, d, p), var in ctx.x.items()
        if var.value() is not None and var.value() > 0.5
    ]
    placements.sort(key=lambda pl: (pl.day, pl.period, pl.course_id))

    violations = validate(spec, placements)
    total = sum(c.weekly_periods for c in spec.courses.values())
    unmet = max(0, total - len(placements))
    objective = pulp.value(problem.objective)

    return SolveResult(
        placements=placements,
        violations=violations,
        status=status,
        objective=float(objective) if objective is not None else 0.0,
        elapsed_sec=elapsed,
        unmet_periods=unmet,
        total_periods=total,
        timed_out=not proven_optimal,
        stats={
            "gap_rel": gap_rel,
            "variables": len(problem.variables()),
            "constraints": len(problem.constraints),
            "courses": len(spec.courses),
            "locked": len(spec.locked),
        },
    )
