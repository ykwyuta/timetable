"""DBモデルと求解エンジンの間をつなぐサービス層。"""

from __future__ import annotations

import math

from sqlalchemy.orm import Session

from . import curriculum as cur
from . import models as m
from .solver.spec import (
    CourseSpec,
    ParallelGroupSpec,
    Placement,
    ProblemSpec,
    TeacherSpec,
)

# 仮定 A-19: 小学校の学級担任は1日の大半を自学級で教えるため、持ちコマ上限を週29コマとする。
# 教科担任・専科は令和4年度教員勤務実態調査の平均18.1コマに合わせて18コマ。
HOMEROOM_MAX_PERIODS_ELEMENTARY = 29
DEFAULT_MAX_PERIODS = 18

MAX_CLASSES = 36  # 要件書 2.1: サポート規模の上限


class GenerationError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 学校の生成
# ---------------------------------------------------------------------------


def generate_school(
    db: Session,
    name: str,
    school_type: str,
    classes_per_grade: int,
    include_special_needs: bool = False,
) -> m.School:
    """校種と1学年あたりの学級数から、学校一式（学級・教員・教科・講座）を生成する。

    生成物はあくまで出発点であり、利用者が画面から編集することを前提にしている。
    """
    if school_type not in cur.GRADES:
        raise GenerationError(f"未知の校種です: {school_type}")
    grades = cur.GRADES[school_type]
    if classes_per_grade < 1:
        raise GenerationError("1学年あたりの学級数は1以上にしてください")
    total_classes = classes_per_grade * len(grades) + (1 if include_special_needs else 0)
    if total_classes > MAX_CLASSES:
        raise GenerationError(
            f"学級数が上限（{MAX_CLASSES}学級）を超えます: {total_classes}学級"
        )

    school = m.School(
        name=name,
        school_type=school_type,
        days=5,
        periods_per_day=cur.PERIODS_PER_DAY[school_type],
        period_minutes=cur.PERIOD_MINUTES[school_type],
    )
    db.add(school)
    db.flush()

    subjects: dict[str, m.Subject] = {}

    def subject_of(subject_name: str) -> m.Subject:
        if subject_name not in subjects:
            meta = cur.SUBJECT_META[subject_name]
            s = m.Subject(
                school_id=school.id,
                name=meta.name,
                short_name=meta.short_name,
                is_core=meta.is_core,
                room_type=meta.room_type,
            )
            db.add(s)
            db.flush()
            subjects[subject_name] = s
        return subjects[subject_name]

    # 学級
    classes: list[m.SchoolClass] = []
    for grade in grades:
        for i in range(classes_per_grade):
            c = m.SchoolClass(
                school_id=school.id, grade=grade, name=f"{grade}年{i + 1}組", kind="normal"
            )
            db.add(c)
            classes.append(c)
    special_class = None
    if include_special_needs:
        special_class = m.SchoolClass(
            school_id=school.id, grade=grades[0], name="特別支援学級", kind="special_needs"
        )
        db.add(special_class)
    db.flush()

    # 学級担任
    homeroom_max = (
        HOMEROOM_MAX_PERIODS_ELEMENTARY
        if school_type == cur.ELEMENTARY
        else DEFAULT_MAX_PERIODS
    )
    homeroom: dict[int, m.Teacher] = {}
    for c in classes + ([special_class] if special_class else []):
        # 特別支援学級の担任は校種によらず全教科を担当するため、上限を高く取る
        limit = (
            HOMEROOM_MAX_PERIODS_ELEMENTARY if c.kind == "special_needs" else homeroom_max
        )
        t = m.Teacher(
            school_id=school.id,
            name=f"{c.name} 担任",
            kind="homeroom",
            max_weekly_periods=limit,
        )
        db.add(t)
        db.flush()
        homeroom[c.id] = t

    # 教科担任・専科。担当学級数ごとに1人を割り当てる
    subject_teachers: dict[tuple[str, int], m.Teacher] = {}

    def classes_per_teacher(configured: int, weekly_periods: int) -> int:
        """担当学級数を持ちコマ上限で頭打ちにする。

        例えば算数専科を6学級担当にすると週30コマとなり、上限18コマを必ず超えて
        しまう。その状態ではソルバーが必ず S3 違反を出す解しか作れない（仮定 A-26）。
        """
        if weekly_periods <= 0:
            return configured
        return max(1, min(configured, DEFAULT_MAX_PERIODS // weekly_periods))

    def teacher_for(subject_name: str, class_index: int, per: int, kind: str) -> m.Teacher:
        bucket = class_index // max(1, per)
        key = (subject_name, bucket)
        if key not in subject_teachers:
            label = "専科" if kind == "specialist" else "教諭"
            t = m.Teacher(
                school_id=school.id,
                name=f"{subject_name} {label}{bucket + 1}",
                kind=kind,
                max_weekly_periods=DEFAULT_MAX_PERIODS,
            )
            db.add(t)
            db.flush()
            subject_teachers[key] = t
        return subject_teachers[key]

    def pick_teacher(
        subject_name: str, klass: m.SchoolClass, class_index: int, periods: int
    ) -> m.Teacher:
        if subject_name in cur.HOMEROOM_SUBJECTS:
            return homeroom[klass.id]
        if school_type == cur.ELEMENTARY:
            configured = cur.ELEMENTARY_SPECIALIST_SUBJECTS.get(subject_name)
            if configured and klass.grade in cur.ELEMENTARY_SPECIALIST_GRADES:
                per = classes_per_teacher(configured, periods)
                return teacher_for(subject_name, class_index, per, "specialist")
            return homeroom[klass.id]
        if school_type == cur.JUNIOR:
            configured = cur.JUNIOR_CLASSES_PER_TEACHER.get(subject_name, 4)
        else:
            configured = cur.HIGH_CLASSES_PER_TEACHER.get(
                subject_name, cur.HIGH_CLASSES_PER_TEACHER_DEFAULT
            )
        return teacher_for(
            subject_name, class_index, classes_per_teacher(configured, periods), "subject"
        )

    def make_course(
        subject_name: str, teacher: m.Teacher, klasses: list[m.SchoolClass], periods: int
    ) -> m.Course:
        meta = cur.SUBJECT_META[subject_name]
        prefers_double = meta.prefers_double and periods >= 2
        course = m.Course(
            school_id=school.id,
            subject_id=subject_of(subject_name).id,
            teacher_id=teacher.id,
            weekly_periods=periods,
            # 週5コマを超える教科は1日2コマまで許容しないと週内に収まらない。
            # 2コマ連続を望む教科（実験・実習）も、1日1コマ制限のままだと
            # S8 の連続配置と S2 が矛盾してしまうため2コマまで許容する
            max_per_day=2 if (periods > 5 or prefers_double) else 1,
            prefers_double=prefers_double,
        )
        course.classes = list(klasses)
        db.add(course)
        db.flush()
        return course

    # 通常学級の講座
    course_by_class_subject: dict[tuple[int, str], m.Course] = {}
    for idx, klass in enumerate(classes):
        weekly = cur.weekly_periods_for(school_type, klass.grade)
        for subject_name, periods in weekly.items():
            teacher = pick_teacher(subject_name, klass, idx, periods)
            course = make_course(subject_name, teacher, [klass], periods)
            course_by_class_subject[(klass.id, subject_name)] = course

    # 高等学校の選択科目群。学級ごとに並列開講する
    if school_type == cur.HIGH:
        for idx, klass in enumerate(classes):
            for group_name, periods, subject_names in cur.HIGH_ELECTIVES.get(klass.grade, []):
                group = m.ParallelGroup(
                    school_id=school.id, name=f"{klass.name} {group_name}"
                )
                db.add(group)
                db.flush()
                members = []
                for subject_name in subject_names:
                    teacher = teacher_for(
                        subject_name,
                        idx,
                        classes_per_teacher(cur.HIGH_CLASSES_PER_TEACHER_DEFAULT, periods),
                        "subject",
                    )
                    members.append(make_course(subject_name, teacher, [klass], periods))
                group.courses = members

    # 特別支援学級。第1学年の教育課程を用いる。
    # 交流及び共同学習の教科は、別講座を作って同時展開させるのではなく、
    # 通常学級の講座に特別支援学級を追加する（＝同じ授業に参加する）。
    # 実態に即しているうえ、教室も教員も二重に数えなくて済む（仮定 A-28）。
    if special_class is not None:
        weekly = cur.weekly_periods_for(school_type, grades[0])
        exchange_subjects = {"体育", "保健体育", "音楽", "図画工作", "美術"}
        for subject_name, periods in weekly.items():
            partner = course_by_class_subject.get((classes[0].id, subject_name))
            if subject_name in exchange_subjects and partner is not None:
                partner.classes = list(partner.classes) + [special_class]
                db.flush()
                continue
            make_course(subject_name, homeroom[special_class.id], [special_class], periods)

    _create_rooms_for_demand(db, school)

    db.commit()
    db.refresh(school)
    return school


# 特別教室の稼働率の目標。1.0（＝需要ぴったり）にすると、その教室を使う授業が
# 全コマ埋まっていないと成立しなくなり、他の制約と両立しなくなる（仮定 A-25）
ROOM_UTILISATION_TARGET = 0.75


def _create_rooms_for_demand(db: Session, school: m.School) -> None:
    """特別教室を、その教科の週コマ数の合計（需要）から必要数だけ用意する。

    固定値にすると、19学級の小学校で理科室1室のような物理的に配置不能な設定に
    なってしまう（理科だけで週36コマ必要なのに枠は週30コマしかない）。
    """
    slots = school.days * school.periods_per_day
    demand: dict[str, int] = {}
    courses = db.query(m.Course).filter(m.Course.school_id == school.id).all()
    for c in courses:
        room_type = c.subject.room_type
        if room_type:
            demand[room_type] = demand.get(room_type, 0) + c.weekly_periods
    baseline = cur.DEFAULT_ROOMS[school.school_type]
    for room_type in sorted(set(demand) | set(baseline)):
        need = demand.get(room_type, 0)
        count = max(
            baseline.get(room_type, 1),
            math.ceil(need / (slots * ROOM_UTILISATION_TARGET)) if need else 1,
        )
        for i in range(count):
            suffix = f"{i + 1}" if count > 1 else ""
            db.add(
                m.Room(school_id=school.id, name=f"{room_type}{suffix}", room_type=room_type)
            )
    db.flush()


# ---------------------------------------------------------------------------
# ProblemSpec の構築
# ---------------------------------------------------------------------------


def build_spec(db: Session, school: m.School, timetable: m.Timetable | None = None) -> ProblemSpec:
    """DBの状態から求解・検証の入力を作る。

    timetable を渡すと、その時間割で固定（ロック）された割当を制約に含める。
    """
    courses = db.query(m.Course).filter(m.Course.school_id == school.id).all()
    teachers = db.query(m.Teacher).filter(m.Teacher.school_id == school.id).all()
    classes = db.query(m.SchoolClass).filter(m.SchoolClass.school_id == school.id).all()
    rooms = db.query(m.Room).filter(m.Room.school_id == school.id).all()
    blocked = db.query(m.BlockedSlot).filter(m.BlockedSlot.school_id == school.id).all()
    groups = db.query(m.ParallelGroup).filter(m.ParallelGroup.school_id == school.id).all()

    room_capacity: dict[str, int] = {}
    for room in rooms:
        room_capacity[room.room_type] = room_capacity.get(room.room_type, 0) + 1

    teacher_specs = {
        t.id: TeacherSpec(
            id=t.id,
            name=t.name,
            max_weekly_periods=t.max_weekly_periods,
            unavailable=frozenset((u.day, u.period) for u in t.unavailabilities),
        )
        for t in teachers
    }

    course_specs = {}
    for c in courses:
        class_names = "・".join(k.name for k in c.classes)
        course_specs[c.id] = CourseSpec(
            id=c.id,
            label=f"{class_names} {c.subject.name}",
            subject_id=c.subject_id,
            subject_name=c.subject.name,
            is_core=bool(c.subject.is_core),
            room_type=c.subject.room_type,
            teacher_id=c.teacher_id,
            class_ids=tuple(k.id for k in c.classes),
            weekly_periods=c.weekly_periods,
            max_per_day=c.max_per_day,
            prefers_double=bool(c.prefers_double),
        )

    locked: set[Placement] = set()
    if timetable is not None:
        for a in timetable.assignments:
            if a.locked:
                locked.add(Placement(course_id=a.course_id, day=a.day, period=a.period))

    return ProblemSpec(
        days=school.days,
        periods_per_day=school.periods_per_day,
        courses=course_specs,
        teachers=teacher_specs,
        class_names={k.id: k.name for k in classes},
        room_capacity=room_capacity,
        blocked=frozenset((b.class_id, b.day, b.period) for b in blocked),
        parallel_groups=tuple(
            ParallelGroupSpec(id=g.id, name=g.name, course_ids=tuple(c.id for c in g.courses))
            for g in groups
        ),
        locked=frozenset(locked),
    )


def placements_of(timetable: m.Timetable) -> list[Placement]:
    return [
        Placement(course_id=a.course_id, day=a.day, period=a.period)
        for a in timetable.assignments
    ]


def replace_assignments(
    db: Session,
    timetable: m.Timetable,
    placements: list[Placement],
    keep_locked: bool = True,
) -> None:
    """時間割の割当を置き換える。固定された割当のロック状態は引き継ぐ。"""
    locked_slots = {
        (a.course_id, a.day, a.period) for a in timetable.assignments if a.locked
    }
    for a in list(timetable.assignments):
        db.delete(a)
    db.flush()
    for pl in placements:
        db.add(
            m.Assignment(
                timetable_id=timetable.id,
                course_id=pl.course_id,
                day=pl.day,
                period=pl.period,
                locked=keep_locked and (pl.course_id, pl.day, pl.period) in locked_slots,
            )
        )
    db.flush()
