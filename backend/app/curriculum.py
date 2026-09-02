"""教育課程マスタ。

小学校・中学校は学校教育法施行規則 別表第一・第二の標準授業時数をそのまま持ち、
週コマ数は「年間授業時数 ÷ 授業週数」を最大剰余法で整数に配分して導出する（仮定 A-14）。
高等学校は単位制で教科ごとの標準時数が定められていないため、必履修科目を中心とした
標準的な教育課程を1つ用意し、標準単位数をそのまま週コマ数として扱う（1単位＝週1コマ。
35単位時間 ÷ 35週 による）。

出典は docs/requirements.md の末尾を参照。
"""

from __future__ import annotations

from dataclasses import dataclass

ELEMENTARY = "elementary"
JUNIOR = "junior"
HIGH = "high"

SCHOOL_TYPE_LABELS = {ELEMENTARY: "小学校", JUNIOR: "中学校", HIGH: "高等学校"}
GRADES = {ELEMENTARY: [1, 2, 3, 4, 5, 6], JUNIOR: [1, 2, 3], HIGH: [1, 2, 3]}
PERIOD_MINUTES = {ELEMENTARY: 45, JUNIOR: 50, HIGH: 50}
PERIODS_PER_DAY = {ELEMENTARY: 6, JUNIOR: 6, HIGH: 6}


@dataclass(frozen=True)
class SubjectMeta:
    name: str
    short_name: str
    is_core: bool = False
    room_type: str | None = None
    prefers_double: bool = False


SUBJECT_META: dict[str, SubjectMeta] = {
    m.name: m
    for m in [
        # 小学校
        SubjectMeta("国語", "国", is_core=True),
        SubjectMeta("社会", "社", is_core=True),
        SubjectMeta("算数", "算", is_core=True),
        SubjectMeta("理科", "理", is_core=True, room_type="理科室", prefers_double=True),
        SubjectMeta("生活", "生"),
        SubjectMeta("音楽", "音", room_type="音楽室"),
        SubjectMeta("図画工作", "図", room_type="図工室", prefers_double=True),
        SubjectMeta("家庭", "家", room_type="家庭科室", prefers_double=True),
        SubjectMeta("体育", "体", room_type="体育館"),
        SubjectMeta("特別の教科 道徳", "道"),
        SubjectMeta("特別活動", "特"),
        SubjectMeta("総合的な学習の時間", "総"),
        SubjectMeta("外国語活動", "外活"),
        SubjectMeta("外国語", "外", is_core=True),
        # 中学校
        SubjectMeta("数学", "数", is_core=True),
        SubjectMeta("美術", "美", room_type="美術室", prefers_double=True),
        SubjectMeta("保健体育", "保体", room_type="体育館"),
        SubjectMeta("技術・家庭", "技家", room_type="技術室", prefers_double=True),
        # 高等学校
        SubjectMeta("現代の国語", "現国", is_core=True),
        SubjectMeta("言語文化", "言文", is_core=True),
        SubjectMeta("論理国語", "論国", is_core=True),
        SubjectMeta("文学国語", "文国", is_core=True),
        SubjectMeta("古典探究", "古探", is_core=True),
        SubjectMeta("地理総合", "地総", is_core=True),
        SubjectMeta("歴史総合", "歴総", is_core=True),
        SubjectMeta("地理探究", "地探", is_core=True),
        SubjectMeta("日本史探究", "日探", is_core=True),
        SubjectMeta("世界史探究", "世探", is_core=True),
        SubjectMeta("公共", "公共", is_core=True),
        SubjectMeta("数学Ⅰ", "数I", is_core=True),
        SubjectMeta("数学Ⅱ", "数II", is_core=True),
        SubjectMeta("数学Ⅲ", "数III", is_core=True),
        SubjectMeta("数学Ａ", "数A", is_core=True),
        SubjectMeta("数学Ｂ", "数B", is_core=True),
        SubjectMeta("化学基礎", "化基", room_type="理科室", prefers_double=True),
        SubjectMeta("生物基礎", "生基", room_type="理科室", prefers_double=True),
        SubjectMeta("物理基礎", "物基", room_type="理科室", prefers_double=True),
        SubjectMeta("化学", "化", room_type="理科室", prefers_double=True),
        SubjectMeta("生物", "生", room_type="理科室", prefers_double=True),
        SubjectMeta("物理", "物", room_type="理科室", prefers_double=True),
        SubjectMeta("体育", "体育", room_type="体育館"),
        SubjectMeta("保健", "保健"),
        SubjectMeta("音楽Ⅰ", "音I", room_type="音楽室"),
        SubjectMeta("英語コミュニケーションⅠ", "英CI", is_core=True),
        SubjectMeta("英語コミュニケーションⅡ", "英CII", is_core=True),
        SubjectMeta("英語コミュニケーションⅢ", "英CIII", is_core=True),
        SubjectMeta("論理・表現Ⅰ", "論表I", is_core=True),
        SubjectMeta("論理・表現Ⅱ", "論表II", is_core=True),
        SubjectMeta("論理・表現Ⅲ", "論表III", is_core=True),
        SubjectMeta("家庭基礎", "家基", room_type="家庭科室", prefers_double=True),
        SubjectMeta("情報Ⅰ", "情I", room_type="PC教室", prefers_double=True),
        SubjectMeta("総合的な探究の時間", "探究"),
    ]
}

# ---------------------------------------------------------------------------
# 標準授業時数（年間）
# ---------------------------------------------------------------------------

ELEMENTARY_ANNUAL_HOURS: dict[int, dict[str, int]] = {
    1: {"国語": 306, "算数": 136, "生活": 102, "音楽": 68, "図画工作": 68, "体育": 102,
        "特別の教科 道徳": 34, "特別活動": 34},
    2: {"国語": 315, "算数": 175, "生活": 105, "音楽": 70, "図画工作": 70, "体育": 105,
        "特別の教科 道徳": 35, "特別活動": 35},
    3: {"国語": 245, "社会": 70, "算数": 175, "理科": 90, "音楽": 60, "図画工作": 60,
        "体育": 105, "特別の教科 道徳": 35, "特別活動": 35, "総合的な学習の時間": 70,
        "外国語活動": 35},
    4: {"国語": 245, "社会": 90, "算数": 175, "理科": 105, "音楽": 60, "図画工作": 60,
        "体育": 105, "特別の教科 道徳": 35, "特別活動": 35, "総合的な学習の時間": 70,
        "外国語活動": 35},
    5: {"国語": 175, "社会": 100, "算数": 175, "理科": 105, "音楽": 50, "図画工作": 50,
        "家庭": 60, "体育": 90, "特別の教科 道徳": 35, "特別活動": 35,
        "総合的な学習の時間": 70, "外国語": 70},
    6: {"国語": 175, "社会": 105, "算数": 175, "理科": 105, "音楽": 50, "図画工作": 50,
        "家庭": 55, "体育": 90, "特別の教科 道徳": 35, "特別活動": 35,
        "総合的な学習の時間": 70, "外国語": 70},
}
ELEMENTARY_TOTAL_HOURS = {1: 850, 2: 910, 3: 980, 4: 1015, 5: 1015, 6: 1015}
ELEMENTARY_WEEKS = {1: 34, 2: 35, 3: 35, 4: 35, 5: 35, 6: 35}

JUNIOR_ANNUAL_HOURS: dict[int, dict[str, int]] = {
    1: {"国語": 140, "社会": 105, "数学": 140, "理科": 105, "音楽": 45, "美術": 45,
        "保健体育": 105, "技術・家庭": 70, "外国語": 140, "特別の教科 道徳": 35,
        "総合的な学習の時間": 50, "特別活動": 35},
    2: {"国語": 140, "社会": 105, "数学": 105, "理科": 140, "音楽": 35, "美術": 35,
        "保健体育": 105, "技術・家庭": 70, "外国語": 140, "特別の教科 道徳": 35,
        "総合的な学習の時間": 70, "特別活動": 35},
    3: {"国語": 105, "社会": 140, "数学": 140, "理科": 140, "音楽": 35, "美術": 35,
        "保健体育": 105, "技術・家庭": 35, "外国語": 140, "特別の教科 道徳": 35,
        "総合的な学習の時間": 70, "特別活動": 35},
}
JUNIOR_TOTAL_HOURS = {1: 1015, 2: 1015, 3: 1015}
JUNIOR_WEEKS = {1: 35, 2: 35, 3: 35}

# 高等学校は単位数＝週コマ数。週30単位時間の標準に合わせて必履修中心に構成した。
HIGH_WEEKLY: dict[int, dict[str, int]] = {
    1: {"現代の国語": 2, "言語文化": 2, "地理総合": 2, "歴史総合": 2, "数学Ⅰ": 3,
        "数学Ａ": 2, "化学基礎": 2, "生物基礎": 2, "体育": 3, "保健": 1, "音楽Ⅰ": 2,
        "英語コミュニケーションⅠ": 3, "論理・表現Ⅰ": 2, "情報Ⅰ": 2},
    2: {"論理国語": 4, "古典探究": 3, "公共": 2, "数学Ⅱ": 4, "数学Ｂ": 2, "体育": 2,
        "保健": 1, "英語コミュニケーションⅡ": 4, "論理・表現Ⅱ": 2, "家庭基礎": 2,
        "総合的な探究の時間": 1},
    3: {"文学国語": 4, "古典探究": 3, "数学Ⅲ": 3, "体育": 3,
        "英語コミュニケーションⅢ": 4, "論理・表現Ⅲ": 2, "総合的な探究の時間": 2},
}

# 高等学校の選択科目群。学年 -> [(群名, 週コマ数, [科目...])]
# 同一時間帯に並列開講し、生徒がどれか1つを選ぶ。
HIGH_ELECTIVES: dict[int, list[tuple[str, int, list[str]]]] = {
    1: [],
    2: [("2年 理科選択", 3, ["物理基礎", "化学基礎", "生物基礎"])],
    3: [
        ("3年 地歴選択", 4, ["日本史探究", "世界史探究", "地理探究"]),
        ("3年 理科選択", 5, ["物理", "化学", "生物"]),
    ],
}

# ---------------------------------------------------------------------------
# 週コマ数の導出
# ---------------------------------------------------------------------------


def annual_to_weekly(annual: dict[str, int], weeks: int, total_hours: int) -> dict[str, int]:
    """年間授業時数を週コマ数に配分する。

    単純に四捨五入すると合計が総授業時数と合わなくなるため、最大剰余法
    （各教科の小数部が大きい順に1コマずつ配る）で合計を一致させる（仮定 A-14）。
    """
    target = round(total_hours / weeks)
    exact = {name: hours / weeks for name, hours in annual.items()}
    base = {name: int(value) for name, value in exact.items()}
    remaining = target - sum(base.values())
    order = sorted(exact, key=lambda n: (-(exact[n] - base[n]), n))
    for name in order:
        if remaining <= 0:
            break
        base[name] += 1
        remaining -= 1
    # 0コマになる教科が出ないよう最低1コマを保証する
    for name in base:
        if base[name] == 0:
            base[name] = 1
    return base


def weekly_periods_for(school_type: str, grade: int) -> dict[str, int]:
    if school_type == ELEMENTARY:
        return annual_to_weekly(
            ELEMENTARY_ANNUAL_HOURS[grade],
            ELEMENTARY_WEEKS[grade],
            ELEMENTARY_TOTAL_HOURS[grade],
        )
    if school_type == JUNIOR:
        return annual_to_weekly(
            JUNIOR_ANNUAL_HOURS[grade], JUNIOR_WEEKS[grade], JUNIOR_TOTAL_HOURS[grade]
        )
    if school_type == HIGH:
        return dict(HIGH_WEEKLY[grade])
    raise ValueError(f"unknown school type: {school_type}")


def total_weekly_periods(school_type: str, grade: int) -> int:
    """選択科目群を含めた週の総コマ数。"""
    total = sum(weekly_periods_for(school_type, grade).values())
    if school_type == HIGH:
        total += sum(n for _, n, _ in HIGH_ELECTIVES.get(grade, []))
    return total


# ---------------------------------------------------------------------------
# 教員配置の実態
# ---------------------------------------------------------------------------

# 小学校高学年の専科指導の優先教科（文部科学省）。値は専科教員1人あたりの担当学級数（仮定 A-16）
ELEMENTARY_SPECIALIST_SUBJECTS = {"外国語": 4, "理科": 4, "算数": 6, "体育": 6}
# 専科指導は高学年から導入されている
ELEMENTARY_SPECIALIST_GRADES = {5, 6}

# 中学校・高等学校の教科担任1人あたりの担当学級数（仮定 A-16）
JUNIOR_CLASSES_PER_TEACHER = {
    "国語": 4, "社会": 5, "数学": 4, "理科": 4, "音楽": 8, "美術": 8,
    "保健体育": 6, "技術・家庭": 8, "外国語": 4,
}
HIGH_CLASSES_PER_TEACHER_DEFAULT = 4
HIGH_CLASSES_PER_TEACHER = {
    "体育": 6, "保健": 8, "音楽Ⅰ": 8, "情報Ⅰ": 8, "家庭基礎": 8,
    "総合的な探究の時間": 8,
}

# 学級担任が担当する教科（教科担任制の校種でも担任が受け持つもの）
HOMEROOM_SUBJECTS = {"特別の教科 道徳", "特別活動", "総合的な学習の時間", "総合的な探究の時間"}

# 特別教室の既定保有数（仮定 A-18）
DEFAULT_ROOMS = {
    ELEMENTARY: {"理科室": 1, "音楽室": 1, "図工室": 1, "家庭科室": 1, "体育館": 1},
    JUNIOR: {"理科室": 2, "音楽室": 1, "美術室": 1, "技術室": 1, "体育館": 1},
    HIGH: {"理科室": 3, "音楽室": 1, "家庭科室": 1, "PC教室": 1, "体育館": 2},
}
