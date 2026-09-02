"""API の統合テスト。提案→手編集→再提案の一連の流れを通す。"""

from __future__ import annotations

import time

import pytest

POLL_TIMEOUT_SEC = 120


def wait_for_job(client, job_id: str) -> dict:
    deadline = time.time() + POLL_TIMEOUT_SEC
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.2)
    raise AssertionError("求解ジョブが時間内に終わりませんでした")


def create_school(client, school_type="junior", classes_per_grade=1, special=False) -> dict:
    r = client.post(
        "/api/schools",
        json={
            "name": "テスト校",
            "school_type": school_type,
            "classes_per_grade": classes_per_grade,
            "include_special_needs": special,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def two_assignments_of_one_class(tt: dict) -> tuple[dict, dict]:
    """同じ学級に属する、別々の講座・別々のコマの割当を2つ返す。"""
    courses = {c["id"]: c for c in tt["courses"]}
    by_class: dict[int, list[dict]] = {}
    for a in tt["assignments"]:
        for class_id in courses[a["course_id"]]["class_ids"]:
            by_class.setdefault(class_id, []).append(a)
    for items in by_class.values():
        for i, first in enumerate(items):
            for second in items[i + 1 :]:
                if first["course_id"] == second["course_id"]:
                    continue
                if (first["day"], first["period"]) != (second["day"], second["period"]):
                    return first, second
    raise AssertionError("同一学級の割当が2つ見つかりません")


def solve_school(client, school_id: int, source: int | None = None, limit: int = 30) -> dict:
    r = client.post(
        f"/api/schools/{school_id}/solve",
        json={"source_timetable_id": source, "time_limit_sec": limit},
    )
    assert r.status_code == 202, r.text
    return wait_for_job(client, r.json()["id"])


# ---------------------------------------------------------------------------


def test_health_and_meta(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    meta = client.get("/api/meta").json()
    assert [s["value"] for s in meta["school_types"]] == ["elementary", "junior", "high"]
    assert meta["max_classes"] == 36
    assert meta["day_names"] == ["月", "火", "水", "木", "金"]
    # 制約は要件書のハード6件・ソフト10件のうち実装済みのものが並ぶ
    codes = {c["code"] for c in meta["constraints"]}
    assert {"H1", "H2", "H3", "H4", "H6", "S1", "S2", "S3", "S4", "S8", "S9"} == codes


@pytest.mark.parametrize(
    "school_type,periods",
    [("elementary", 6), ("junior", 6), ("high", 6)],
)
def test_create_school_for_each_type(client, school_type: str, periods: int) -> None:
    school = create_school(client, school_type)
    assert school["periods_per_day"] == periods
    assert school["class_count"] >= 3
    assert school["course_count"] > 0


def test_create_school_rejects_too_many_classes(client) -> None:
    r = client.post(
        "/api/schools",
        json={
            "name": "巨大校",
            "school_type": "elementary",
            "classes_per_grade": 7,  # 7 x 6学年 = 42学級 > 上限36
            "include_special_needs": False,
        },
    )
    assert r.status_code == 400
    assert "上限" in r.json()["detail"]


def test_solve_produces_timetable_without_hard_violations(client) -> None:
    school = create_school(client, "junior", classes_per_grade=2)
    job = solve_school(client, school["id"])
    assert job["status"] == "succeeded", job
    assert job["unmet_periods"] == 0

    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()
    assert tt["summary"]["hard_violations"] == 0
    assert tt["summary"]["placed_periods"] == tt["summary"]["total_periods"]
    assert len(tt["assignments"]) > 0
    assert tt["school"]["school_type_label"] == "中学校"


def test_elementary_special_needs_class_shares_exchange_lessons(client) -> None:
    """交流及び共同学習の教科は、通常学級と同じ講座に特別支援学級が入る。"""
    school = create_school(client, "elementary", classes_per_grade=1, special=True)
    job = solve_school(client, school["id"])
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()

    special = next(k for k in tt["classes"] if k["kind"] == "special_needs")
    shared = [c for c in tt["courses"] if special["id"] in c["class_ids"] and len(c["class_ids"]) > 1]
    assert shared, "交流及び共同学習の講座がありません"
    assert {c["subject_name"] for c in shared} & {"体育", "音楽", "図画工作"}


def test_high_school_electives_are_aligned(client) -> None:
    """高校の選択科目群が同一コマに並列開講される。"""
    school = create_school(client, "high", classes_per_grade=1)
    job = solve_school(client, school["id"], limit=60)
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()

    groups = tt["parallel_groups"]
    assert groups, "選択科目群が生成されていません"
    slots_by_course: dict[int, set] = {}
    for a in tt["assignments"]:
        slots_by_course.setdefault(a["course_id"], set()).add((a["day"], a["period"]))
    for g in groups:
        member_slots = [slots_by_course.get(cid, set()) for cid in g["course_ids"]]
        assert all(s == member_slots[0] for s in member_slots), g["name"]


def test_manual_move_creates_and_clears_violation(client) -> None:
    """ドラッグで動かすと違反が出て、戻すと消える（手編集の即時検証）。"""
    school = create_school(client, "junior", classes_per_grade=1)
    job = solve_school(client, school["id"])
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()
    assert tt["summary"]["hard_violations"] == 0

    # 同じ学級の別の割当と同じコマへ動かす
    first, second = two_assignments_of_one_class(tt)
    original = (first["day"], first["period"])
    r = client.patch(
        f"/api/timetables/{tt['id']}/assignments/{first['id']}",
        json={"day": second["day"], "period": second["period"]},
    )
    assert r.status_code == 200
    moved = r.json()
    assert moved["summary"]["hard_violations"] >= 1
    assert any(v["code"] in ("H1", "H2") for v in moved["violations"])

    # 元に戻すと違反が消える
    r = client.patch(
        f"/api/timetables/{tt['id']}/assignments/{first['id']}",
        json={"day": original[0], "period": original[1]},
    )
    assert r.json()["summary"]["hard_violations"] == 0


def test_lock_prevents_move_and_delete(client) -> None:
    school = create_school(client, "junior", classes_per_grade=1)
    job = solve_school(client, school["id"])
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()
    a = tt["assignments"][0]

    locked = client.post(
        f"/api/timetables/{tt['id']}/assignments/{a['id']}/lock", json={"locked": True}
    ).json()
    assert locked["summary"]["locked"] == 1

    r = client.patch(
        f"/api/timetables/{tt['id']}/assignments/{a['id']}", json={"day": 4, "period": 5}
    )
    assert r.status_code == 409
    r = client.delete(f"/api/timetables/{tt['id']}/assignments/{a['id']}")
    assert r.status_code == 409


def test_resolve_keeps_locked_cells(client) -> None:
    """固定したコマを保ったまま残りを再提案する（微調整の中核機能）。"""
    school = create_school(client, "junior", classes_per_grade=2)
    job = solve_school(client, school["id"])
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()

    targets = tt["assignments"][:5]
    for a in targets:
        client.post(
            f"/api/timetables/{tt['id']}/assignments/{a['id']}/lock", json={"locked": True}
        )
    locked_slots = {(a["course_id"], a["day"], a["period"]) for a in targets}

    job2 = solve_school(client, school["id"], source=tt["id"])
    assert job2["status"] == "succeeded", job2
    tt2 = client.get(f"/api/timetables/{job2['timetable_id']}").json()

    new_slots = {(a["course_id"], a["day"], a["period"]) for a in tt2["assignments"]}
    assert locked_slots <= new_slots, "固定した割当が再提案で動いてしまいました"
    assert tt2["parent_id"] == tt["id"]
    assert tt2["summary"]["locked"] == len(targets)


def test_resolve_reports_conflicting_locks(client) -> None:
    """矛盾する固定を作った状態で再提案すると、理由付きで失敗する。"""
    school = create_school(client, "junior", classes_per_grade=1)
    job = solve_school(client, school["id"])
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()

    a, b = two_assignments_of_one_class(tt)
    # 同じコマに重ねてから両方を固定する
    client.patch(
        f"/api/timetables/{tt['id']}/assignments/{a['id']}",
        json={"day": b["day"], "period": b["period"]},
    )
    for x in (a, b):
        client.post(
            f"/api/timetables/{tt['id']}/assignments/{x['id']}/lock", json={"locked": True}
        )

    job2 = solve_school(client, school["id"], source=tt["id"])
    assert job2["status"] == "failed"
    assert "固定" in job2["error"]
    assert any(v["code"] in ("H1", "H2") for v in job2["violations"])


def test_replace_assignments_supports_undo(client) -> None:
    """割当の一括置換。フロントの undo/redo が使う。"""
    school = create_school(client, "junior", classes_per_grade=1)
    job = solve_school(client, school["id"])
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()
    snapshot = [
        {"course_id": a["course_id"], "day": a["day"], "period": a["period"], "locked": a["locked"]}
        for a in tt["assignments"]
    ]

    # 全部消してから、スナップショットで復元する
    client.put(f"/api/timetables/{tt['id']}/assignments", json={"assignments": []})
    empty = client.get(f"/api/timetables/{tt['id']}").json()
    assert empty["summary"]["placed_periods"] == 0
    assert empty["summary"]["unmet_periods"] == empty["summary"]["total_periods"]

    restored = client.put(
        f"/api/timetables/{tt['id']}/assignments", json={"assignments": snapshot}
    ).json()
    assert restored["summary"]["placed_periods"] == tt["summary"]["placed_periods"]
    assert restored["summary"]["hard_violations"] == 0


def test_unplaced_courses_are_reported(client) -> None:
    school = create_school(client, "junior", classes_per_grade=1)
    job = solve_school(client, school["id"])
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()
    assert tt["unplaced"] == []

    a = tt["assignments"][0]
    after = client.delete(f"/api/timetables/{tt['id']}/assignments/{a['id']}").json()
    assert after["unplaced"] == [{"course_id": a["course_id"], "remaining": 1}]


def test_teacher_unavailability_is_applied_on_resolve(client) -> None:
    """教員の不在枠を登録して再提案すると、その枠に授業が入らない。"""
    school = create_school(client, "junior", classes_per_grade=1)
    job = solve_school(client, school["id"])
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()

    teacher = next(t for t in tt["teachers"] if t["kind"] == "subject")
    unavailable = [{"day": 0, "period": p} for p in range(6)]  # 月曜終日不在
    r = client.patch(
        f"/api/teachers/{teacher['id']}", json={"unavailable": unavailable}
    )
    assert r.status_code == 200
    assert len(r.json()["unavailable"]) == 6

    job2 = solve_school(client, school["id"])
    tt2 = client.get(f"/api/timetables/{job2['timetable_id']}").json()
    their_courses = {c["id"] for c in tt2["courses"] if c["teacher_id"] == teacher["id"]}
    assert not [
        a for a in tt2["assignments"] if a["course_id"] in their_courses and a["day"] == 0
    ]


def test_csv_export_by_class_and_teacher(client) -> None:
    school = create_school(client, "junior", classes_per_grade=1)
    job = solve_school(client, school["id"])
    tt_id = job["timetable_id"]

    for by in ("class", "teacher"):
        r = client.get(f"/api/timetables/{tt_id}/export.csv?by={by}")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        body = r.text
        assert "対象,曜日,1限" in body
        assert "月" in body
        assert len(body.splitlines()) > 5


def test_timetable_versions_are_listed(client) -> None:
    school = create_school(client, "junior", classes_per_grade=1)
    solve_school(client, school["id"])
    solve_school(client, school["id"])
    rows = client.get(f"/api/schools/{school['id']}/timetables").json()
    assert len(rows) == 2
    assert rows[0]["name"] == "提案 v2"


def test_duplicate_placement_of_same_course_is_rejected(client) -> None:
    """同じ講座を同じコマに二重に置く操作は弾く。"""
    school = create_school(client, "junior", classes_per_grade=1)
    job = solve_school(client, school["id"])
    tt = client.get(f"/api/timetables/{job['timetable_id']}").json()
    by_course: dict[int, list[dict]] = {}
    for a in tt["assignments"]:
        by_course.setdefault(a["course_id"], []).append(a)
    same_course = next(v for v in by_course.values() if len(v) >= 2)
    a, b = same_course[0], same_course[1]

    r = client.patch(
        f"/api/timetables/{tt['id']}/assignments/{a['id']}",
        json={"day": b["day"], "period": b["period"]},
    )
    assert r.status_code == 409
    r = client.post(
        f"/api/timetables/{tt['id']}/assignments",
        json={"course_id": a["course_id"], "day": a["day"], "period": a["period"]},
    )
    assert r.status_code == 409


def test_not_found_paths(client) -> None:
    assert client.get("/api/timetables/9999").status_code == 404
    assert client.get("/api/jobs/deadbeef").status_code == 404
    assert client.get("/api/schools/9999/timetables").status_code == 404
    assert client.delete("/api/schools/9999").status_code == 404
