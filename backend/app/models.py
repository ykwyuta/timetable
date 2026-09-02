"""SQLAlchemy モデル。

割当の単位は「学級×教科」ではなく Course（講座）である（仮定 A-02）。
Course は担当教員1名と受講学級1つ以上を持ち、小中では 1学級＝1講座 に縮退する。
高校の選択科目の同時展開と、特別支援学級の交流及び共同学習は、
どちらも ParallelGroup（同時展開群）で表現する。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# 講座と受講学級の多対多。高校の選択科目では1講座を複数学級の生徒が受講する。
course_class = Table(
    "course_class",
    Base.metadata,
    Column("course_id", ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
    Column("class_id", ForeignKey("school_classes.id", ondelete="CASCADE"), primary_key=True),
)

parallel_group_course = Table(
    "parallel_group_course",
    Base.metadata,
    Column("group_id", ForeignKey("parallel_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("course_id", ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
)


class School(Base):
    __tablename__ = "schools"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    # "elementary" | "junior" | "high"
    school_type = Column(String, nullable=False)
    days = Column(Integer, nullable=False, default=5)
    periods_per_day = Column(Integer, nullable=False, default=6)
    # 表示用。求解には使わない（仮定 A-08）
    period_minutes = Column(Integer, nullable=False, default=50)

    classes = relationship("SchoolClass", back_populates="school", cascade="all, delete-orphan")
    teachers = relationship("Teacher", back_populates="school", cascade="all, delete-orphan")
    subjects = relationship("Subject", back_populates="school", cascade="all, delete-orphan")
    courses = relationship("Course", back_populates="school", cascade="all, delete-orphan")
    rooms = relationship("Room", back_populates="school", cascade="all, delete-orphan")
    timetables = relationship("Timetable", back_populates="school", cascade="all, delete-orphan")
    blocked_slots = relationship("BlockedSlot", cascade="all, delete-orphan")
    parallel_groups = relationship("ParallelGroup", cascade="all, delete-orphan")


class SchoolClass(Base):
    __tablename__ = "school_classes"

    id = Column(Integer, primary_key=True)
    school_id = Column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)
    grade = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    # "normal" | "special_needs"
    kind = Column(String, nullable=False, default="normal")

    school = relationship("School", back_populates="classes")


class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True)
    school_id = Column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    # "homeroom"（学級担任） | "specialist"（専科） | "subject"（教科担任） | "part_time"（非常勤）
    kind = Column(String, nullable=False, default="subject")
    # 週の持ちコマ数上限。既定18は令和4年度教員勤務実態調査の平均18.1コマに基づく
    max_weekly_periods = Column(Integer, nullable=False, default=18)

    school = relationship("School", back_populates="teachers")
    unavailabilities = relationship(
        "TeacherUnavailability", back_populates="teacher", cascade="all, delete-orphan"
    )


class TeacherUnavailability(Base):
    """教員の不在枠。非常勤講師の勤務曜日制限、出張、育休の代替等を表す。"""

    __tablename__ = "teacher_unavailabilities"
    __table_args__ = (UniqueConstraint("teacher_id", "day", "period"),)

    id = Column(Integer, primary_key=True)
    teacher_id = Column(ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    day = Column(Integer, nullable=False)
    period = Column(Integer, nullable=False)

    teacher = relationship("Teacher", back_populates="unavailabilities")


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True)
    school_id = Column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    short_name = Column(String, nullable=False)
    # 主要教科は午前に寄せる（ソフト制約 S9）
    is_core = Column(Boolean, nullable=False, default=False)
    # この教科が必要とする特別教室の種別。None は普通教室
    room_type = Column(String, nullable=True)

    school = relationship("School", back_populates="subjects")


class Room(Base):
    """特別教室。個々の教室を割り当てるのではなく、種別ごとの同時使用数を制限する（仮定 A-10）。"""

    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True)
    school_id = Column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    room_type = Column(String, nullable=False)

    school = relationship("School", back_populates="rooms")


class Course(Base):
    """講座。時間割のセルに入る単位。"""

    __tablename__ = "courses"

    id = Column(Integer, primary_key=True)
    school_id = Column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)
    subject_id = Column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    teacher_id = Column(ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    weekly_periods = Column(Integer, nullable=False)
    # 1日に同じ講座を置ける上限。週5コマ超の教科は2を既定にする
    max_per_day = Column(Integer, nullable=False, default=1)
    # 2コマ連続を優先する（実験・実習・体育など。ソフト制約 S8）
    prefers_double = Column(Boolean, nullable=False, default=False)

    school = relationship("School", back_populates="courses")
    subject = relationship("Subject")
    teacher = relationship("Teacher")
    classes = relationship("SchoolClass", secondary=course_class)


class ParallelGroup(Base):
    """同時展開群。群に属する講座は同一のコマに配置される。

    高校の選択科目（S4）と、特別支援学級の交流及び共同学習（S5）の両方を表す。
    """

    __tablename__ = "parallel_groups"

    id = Column(Integer, primary_key=True)
    school_id = Column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)

    courses = relationship("Course", secondary=parallel_group_course)


class BlockedSlot(Base):
    """配置禁止枠。class_id が None なら全学級に適用する。"""

    __tablename__ = "blocked_slots"

    id = Column(Integer, primary_key=True)
    school_id = Column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)
    class_id = Column(ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=True)
    day = Column(Integer, nullable=False)
    period = Column(Integer, nullable=False)
    reason = Column(String, nullable=False, default="")


class Timetable(Base):
    """時間割のバージョン。提案→手編集→再提案の履歴を親子関係で保持する。"""

    __tablename__ = "timetables"

    id = Column(Integer, primary_key=True)
    school_id = Column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    parent_id = Column(ForeignKey("timetables.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)

    school = relationship("School", back_populates="timetables")
    assignments = relationship(
        "Assignment", back_populates="timetable", cascade="all, delete-orphan"
    )


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True)
    timetable_id = Column(ForeignKey("timetables.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    day = Column(Integer, nullable=False)
    period = Column(Integer, nullable=False)
    # 固定（ロック）。再提案時にこの割当は動かさない
    locked = Column(Boolean, nullable=False, default=False)

    timetable = relationship("Timetable", back_populates="assignments")
    course = relationship("Course")
