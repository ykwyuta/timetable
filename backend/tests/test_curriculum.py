"""教育課程マスタのテスト。

学校教育法施行規則の標準授業時数と、そこから導出した週コマ数が一致することを確かめる。
"""

from __future__ import annotations

import pytest

from app import curriculum as cur


@pytest.mark.parametrize(
    "grade,expected",
    [(1, 25), (2, 26), (3, 28), (4, 29), (5, 29), (6, 29)],
)
def test_elementary_weekly_periods_match_official_totals(grade: int, expected: int) -> None:
    """小学校の週コマ数が年間標準授業時数 ÷ 授業週数に一致する。"""
    assert sum(cur.weekly_periods_for(cur.ELEMENTARY, grade).values()) == expected


@pytest.mark.parametrize("grade", [1, 2, 3])
def test_junior_weekly_periods_are_29(grade: int) -> None:
    """中学校は全学年 1015時間 ÷ 35週 = 週29コマ。"""
    assert sum(cur.weekly_periods_for(cur.JUNIOR, grade).values()) == 29


@pytest.mark.parametrize("grade", [1, 2, 3])
def test_high_weekly_periods_are_30(grade: int) -> None:
    """高等学校は全日制の標準である週30単位時間に収まる。"""
    assert cur.total_weekly_periods(cur.HIGH, grade) == 30


def test_annual_totals_match_regulation() -> None:
    """マスタに持っている年間授業時数の合計が、施行規則の合計と一致する。"""
    for grade, hours in cur.ELEMENTARY_ANNUAL_HOURS.items():
        extra = 0
        if grade >= 3:
            extra = 0  # 総合・外国語活動も表に含めてある
        assert sum(hours.values()) + extra == cur.ELEMENTARY_TOTAL_HOURS[grade], grade
    for grade, hours in cur.JUNIOR_ANNUAL_HOURS.items():
        assert sum(hours.values()) == cur.JUNIOR_TOTAL_HOURS[grade], grade


def test_no_subject_gets_zero_periods() -> None:
    """どの教科も週0コマにならない（配当されない教科が出ないこと）。"""
    for school_type in (cur.ELEMENTARY, cur.JUNIOR, cur.HIGH):
        for grade in cur.GRADES[school_type]:
            weekly = cur.weekly_periods_for(school_type, grade)
            assert all(n >= 1 for n in weekly.values()), (school_type, grade, weekly)


def test_every_subject_has_metadata() -> None:
    """教育課程に出てくる教科名がすべて SUBJECT_META に定義されている。"""
    names = set()
    for school_type in (cur.ELEMENTARY, cur.JUNIOR, cur.HIGH):
        for grade in cur.GRADES[school_type]:
            names |= set(cur.weekly_periods_for(school_type, grade))
    for electives in cur.HIGH_ELECTIVES.values():
        for _, _, subjects in electives:
            names |= set(subjects)
    missing = names - set(cur.SUBJECT_META)
    assert not missing, f"SUBJECT_META に未定義の教科: {missing}"
