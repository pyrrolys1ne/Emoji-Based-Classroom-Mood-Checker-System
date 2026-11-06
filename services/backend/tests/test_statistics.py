import csv
import io
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.domain import Emotion, Role
from app.db.models import AppUser, AuditLog, ClassSession, Course, EmojiRecord
from app.repositories.statistics import StatisticsRepository
from app.services import record_scope
from app.services.statistics import csv_value

PATHS = ("/api/emoji/statistics", "/api/admin/statistics", "/api/admin/emoji/export")


@pytest.fixture
def dataset(actors):
    client, admin = actors["client"], actors["headers"]["admin"]
    classes = []
    start = datetime(2026, 11, 1, 8, tzinfo=timezone.utc)
    for index, teacher in enumerate(("teacher-a", "teacher-b", "teacher-a")):
        course = client.post("/api/admin/courses", headers=admin, json={
            "name": "统计课程" + str(index), "teacherId": actors["users"][teacher]["id"],
        }).json()["data"]
        response = client.post("/api/admin/sessions", headers=admin, json={
            "courseId": course["id"], "startsAt": start.isoformat(),
            "endsAt": (start + timedelta(hours=6)).isoformat(), "room": "101", "className": "统计班" + str(index),
        })
        assert response.status_code == 200, response.text
        classes.append(response.json()["data"])
    rows = [
        (0, "student-a", "HAPPY", "MANUAL", "2026-11-01T09:05:00Z", False),
        (0, "student-b", "SAD", "MANUAL", "2026-11-01T10:05:00Z", False),
        (0, None, "HAPPY", "AI", "2026-11-01T09:05:30Z", False),
        (0, None, "NEUTRAL", "AI", "2026-11-01T11:05:00Z", True),
        (1, "student-b", "ANGRY", "MANUAL", "2026-11-01T09:10:00Z", False),
        (2, "student-a", "FOCUSED", "MANUAL", "2026-11-02T09:05:00Z", False),
    ]
    ids = []
    with actors["factory"].begin() as session:
        for index, who, emotion, source, recorded, simulated in rows:
            record = EmojiRecord(id=uuid4(), session_id=UUID(classes[index]["id"]),
                user_id=UUID(actors["users"][who]["id"]) if who else None,
                emotion=emotion, source=source, recorded_at=datetime.fromisoformat(recorded), simulated=simulated,
                confidence=0.8 if source == "AI" else None, device_id="test-camera" if source == "AI" else None,
                inference_provider="DeepSeek" if source == "AI" else None,
                confidence_kind="self_reported" if source == "AI" else None)
            session.add(record)
            ids.append(str(record.id))
    return {**actors, "classes": classes, "ids": ids}


def get(data, path, who="admin", **filters):
    return data["client"].get(path, headers=data["headers"][who], params=filters)


def parsed(response):
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"), newline="")))


def test_default_manual_and_explicit_source_match_across_endpoints(dataset):
    for source, total in ((None, 4), ("MANUAL", 4), ("AI", 1), ("ALL", 5)):
        filters = {} if source is None else {"source": source}
        basic = get(dataset, PATHS[0], **filters).json()["data"]
        multi = get(dataset, PATHS[1], **filters).json()["data"]
        exported = parsed(get(dataset, PATHS[2], **filters))
        history = get(dataset, "/api/emoji/history", source=source or "MANUAL").json()["data"]
        assert basic["total"] == multi["total"] == len(exported) == len(history) == total
        assert set(basic["distribution"]) == {emotion.value for emotion in Emotion}
        assert sum(basic["distribution"].values()) == total
        assert multi["distribution"] == basic["distribution"] and basic["source"] == (source or "MANUAL")
        assert sum(item["total"] for item in multi["timeline"]) == total
        assert sum(item["total"] for item in multi["groups"]) == total
        assert {row["记录编号"] for row in exported} == {row["id"] for row in history}


def test_roles_explicit_scope_and_removed_roster(dataset):
    for path in PATHS:
        assert get(dataset, path, "student-a").status_code == 403
        assert dataset["client"].get(path).status_code == 401
        assert dataset["client"].get(path, headers={"Authorization": "Bearer synthetic-ai-service"}).status_code == 401
    assert get(dataset, PATHS[2], "teacher-a").status_code == 403
    assert get(dataset, PATHS[0], "teacher-a").json()["data"]["total"] == 3
    assert get(dataset, PATHS[0], "teacher-b").json()["data"]["total"] == 1
    for path in PATHS[:2]:
        assert get(dataset, path, "teacher-a", sessionId=dataset["classes"][1]["id"]).status_code == 403
        assert get(dataset, path, "teacher-a", course=dataset["classes"][1]["courseId"]).json()["data"]["total"] == 0
        assert get(dataset, path, "teacher-b", userId=dataset["users"]["student-a"]["id"]).json()["data"]["total"] == 0
        assert get(dataset, path, sessionId=str(uuid4())).status_code == 404
    assert parsed(get(dataset, PATHS[2], sessionId=dataset["classes"][0]["id"]))[0]["用户"] == "student-b姓名"


@pytest.mark.parametrize("filters,expected", [
    ({"emotion": "HAPPY", "source": "ALL"}, 2),
    ({"class": "统计班0"}, 2), ({"class": "不存在"}, 0),
    ({"from": "2026-11-01T17:05:00+08:00", "to": "2026-11-01T10:05:00Z", "source": "ALL"}, 2),
    ({"from": "2026-11-01T10:05:00Z", "to": "2026-11-02T09:05:00Z"}, 1),
])
def test_common_filters_and_half_open_time_ranges(dataset, filters, expected):
    if "class" not in filters:
        filters = {"sessionId": dataset["classes"][0]["id"], **filters}
    for path in PATHS[:2]:
        response = get(dataset, path, **filters)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["total"] == expected
    assert len(parsed(get(dataset, PATHS[2], **filters))) == expected


def test_course_student_and_emotion_filters_intersect(dataset):
    filters = {"course": dataset["classes"][0]["courseId"], "userId": dataset["users"]["student-a"]["id"], "emotion": "HAPPY", "source": "ALL"}
    assert get(dataset, PATHS[1], **filters).json()["data"]["total"] == 1
    exported = parsed(get(dataset, PATHS[2], **filters))
    assert [row["记录编号"] for row in exported] == [dataset["ids"][0]]
    filters["emotion"] = "SAD"
    assert get(dataset, PATHS[0], **filters).json()["data"]["total"] == 0


def test_timeline_uses_absolute_time_across_hours_days_and_offsets(dataset):
    result = get(dataset, PATHS[1], "teacher-a", source="ALL").json()["data"]
    assert len(result["timeline"]) <= 12
    assert sum(bucket["total"] for bucket in result["timeline"]) == result["total"] == 4
    assert result["timeline"][0]["total"] == 3 and result["timeline"][-1]["total"] == 1
    assert any(bucket["total"] == 0 for bucket in result["timeline"])
    filtered = get(dataset, PATHS[1], sessionId=dataset["classes"][0]["id"], source="MANUAL").json()["data"]
    populated = [bucket for bucket in filtered["timeline"] if bucket["total"]]
    assert len(populated) == 2
    assert all(datetime.fromisoformat(a["endsAt"]) == datetime.fromisoformat(b["startsAt"]) for a, b in zip(filtered["timeline"], filtered["timeline"][1:]))
    empty = get(dataset, PATHS[1], emotion="CONFUSED").json()["data"]
    assert empty["timeline"] == empty["groups"] == [] and empty["total"] == 0


def test_simulated_rows_follow_environment_policy(dataset, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_simulated_ai", True)
    assert get(dataset, PATHS[1], source="AI").json()["data"]["total"] == 2
    rows = parsed(get(dataset, PATHS[2], source="AI"))
    assert {row["模拟输入"] for row in rows} == {"是", "否"}
    assert all(row["用户编号"] == row["学号"] == "" and row["用户"] == "匿名" for row in rows)
    assert all(row["模型分数"] == "0.8" and row["分数类型"] == "self_reported" and row["推理提供方"] == "DeepSeek" for row in rows)
    assert all(row["设备标识"] == "test-camera" for row in rows)


@pytest.mark.parametrize("filters", [{"source": "unknown"}, {"from": "2026-11-01T09:00:00"},
    {"from": "2026-11-02T00:00:00Z", "to": "2026-11-01T00:00:00Z"},
    {"from": "2026-11-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"},
    {"sessionId": "invalid"}, {"course": "invalid"}, {"emotion": "unknown"}, {"limit": 1}, {"userId": "invalid"}])
def test_invalid_filters_never_fall_back_to_full_data(dataset, filters):
    for path in PATHS:
        assert get(dataset, path, **filters).status_code == 422
    assert get(dataset, PATHS[2], format="json").status_code == 422


def test_large_dataset_is_aggregated_and_exported_completely(dataset):
    with dataset["factory"].begin() as session:
        session.add_all(EmojiRecord(id=UUID(int=100 + index), session_id=UUID(dataset["classes"][0]["id"]),
            user_id=UUID(dataset["users"]["student-a"]["id"]), emotion="CONFUSED", source="MANUAL",
            recorded_at=datetime(2026, 11, 3, tzinfo=timezone.utc)) for index in range(1101))
    filters = {"emotion": "CONFUSED"}
    assert get(dataset, PATHS[0], **filters).json()["data"]["total"] == 1101
    result = get(dataset, PATHS[1], **filters).json()["data"]
    assert result["total"] == result["timeline"][0]["total"] == result["groups"][0]["total"] == 1101
    rows = parsed(get(dataset, PATHS[2], **filters))
    assert len(rows) == 1101
    assert [row["记录编号"] for row in rows] == [str(UUID(int=100 + index)) for index in range(1100, -1, -1)]


def test_csv_quotes_newlines_unicode_and_formula_injection(dataset):
    with dataset["factory"].begin() as session:
        user = session.get(AppUser, UUID(dataset["users"]["student-a"]["id"]))
        user.real_name = ' \t=HYPERLINK("危险")\r\n中文,姓名'
        user.student_no = '@SUM(1,2)'
        classroom = session.get(ClassSession, UUID(dataset["classes"][0]["id"]))
        classroom.class_name = '\n+命令,"班级"'
        course = session.get(Course, classroom.course_id)
        course.name = '-公式,课程'
    rows = parsed(get(dataset, PATHS[2], emotion="HAPPY"))
    assert len(rows) == 1
    assert rows[0]["用户"] == '\' \t=HYPERLINK("危险")\r\n中文,姓名'
    assert rows[0]["学号"] == "'@SUM(1,2)" and rows[0]["课程"] == "'-公式,课程"
    assert rows[0]["班级"] == '\'\n+命令,"班级"'
    response = get(dataset, PATHS[2], emotion="CONFUSED")
    assert parsed(response) == [] and 'attachment;' in response.headers["Content-Disposition"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_csv_audit_failure_returns_json_and_no_file(dataset, monkeypatch):
    def fail(*args):
        raise RuntimeError("private-export-failure")
    monkeypatch.setattr(StatisticsRepository, "audit_export", fail)
    response = get(dataset, PATHS[2])
    assert response.status_code == 500 and response.headers["Content-Type"] == "application/json"
    assert "private-export-failure" not in response.text and "Content-Disposition" not in response.headers
    with dataset["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "EMOJI_CSV_EXPORT")) == 0


def test_statistics_and_export_recheck_role_after_authentication(dataset, monkeypatch):
    original = record_scope.authorize_actor
    def changed(repo, principal, **kwargs):
        with dataset["factory"].begin() as session:
            session.get(AppUser, principal.user.id).role = Role.STUDENT
        return original(repo, principal, **kwargs)
    monkeypatch.setattr(record_scope, "authorize_actor", changed)
    assert get(dataset, PATHS[0], "teacher-a").status_code == 403
    assert get(dataset, PATHS[2]).status_code == 403


@pytest.mark.parametrize("text", ["=1", "+1", "-1", "@SUM(A1)", " \t=1", "\tcmd", "\rcmd", "\ncmd", "\ufeff=1"])
def test_csv_formula_prefixes_are_neutralized(text):
    assert csv_value(text) == "'" + text
