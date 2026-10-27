import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5


def fixture_id(name: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"mood-integration-{name}"))


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self):
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection

    def initialize(self):
        with self.connection() as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE, role TEXT, email TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, data TEXT NOT NULL, teacher_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, event_key TEXT UNIQUE, data TEXT NOT NULL, session_id TEXT REFERENCES sessions(id));
            """)
            if connection.execute("SELECT count(*) FROM users").fetchone()[0]:
                return
            names = ["林晓", "陈雨", "李明", "王悦", "张晨", "刘洋", "赵宁", "周可"]
            users = [
                (
                    fixture_id(f"student-{index}"),
                    name,
                    "STUDENT",
                    f"student{index}@example.edu",
                    "ACTIVE",
                )
                for index, name in enumerate(names)
            ]
            users += [
                (fixture_id("admin"), "admin", "ADMIN", "admin@example.edu", "ACTIVE"),
                (
                    fixture_id("teacher"),
                    "teacher",
                    "TEACHER",
                    "teacher@example.edu",
                    "ACTIVE",
                ),
            ]
            connection.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?)", users)
            now = datetime.now(timezone.utc)
            for index, course in enumerate(["软件工程实践", "数据库系统"]):
                session = {
                    "id": fixture_id(f"session-{index}"),
                    "courseId": fixture_id(f"course-{index}"),
                    "courseName": course,
                    "teacherName": "陈老师" if index == 0 else "其他教师",
                    "className": f"软件工程 230{index + 1}",
                    "room": "实训楼 302",
                    "startsAt": (now - timedelta(minutes=30)).isoformat(),
                    "endsAt": (now + timedelta(hours=2)).isoformat(),
                    "scheduledUserIds": [user[0] for user in users[:8]],
                }
                teacher = (
                    fixture_id("teacher") if index == 0 else fixture_id("other-teacher")
                )
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?)",
                    (session["id"], json.dumps(session), teacher),
                )

    def users(self):
        with self.connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM users")]

    def sessions(self, teacher_id: str | None = None):
        with self.connection() as connection:
            rows = (
                connection.execute(
                    "SELECT data FROM sessions WHERE teacher_id = ?", (teacher_id,)
                )
                if teacher_id
                else connection.execute("SELECT data FROM sessions")
            )
            return [json.loads(row[0]) for row in rows]

    def schedule(self, session_id: str, user_ids: list[str]):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT data FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            data = json.loads(row[0])
            data["scheduledUserIds"] = list(dict.fromkeys(user_ids))
            connection.execute(
                "UPDATE sessions SET data = ? WHERE id = ?",
                (json.dumps(data), session_id),
            )

    def records(self, allowed_sessions: set[str]):
        with self.connection() as connection:
            return [
                json.loads(row["data"])
                for row in connection.execute(
                    "SELECT session_id, data FROM records ORDER BY rowid DESC"
                )
                if row["session_id"] in allowed_sessions
            ]

    def insert(self, record: dict, event_key: str):
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT data FROM records WHERE event_key = ?", (event_key,)
            ).fetchone()
            if existing:
                previous = json.loads(existing[0])
                # 同一幂等键不得绑定另一份结果。
                if any(
                    previous.get(key) != record.get(key)
                    for key in (
                        "sessionId",
                        "emotion",
                        "confidence",
                        "recordedAt",
                        "deviceId",
                        "simulated",
                    )
                ):
                    raise ValueError("幂等键对应的结果不一致")
                return previous, False
            connection.execute(
                "INSERT INTO records VALUES (?, ?, ?, ?)",
                (record["id"], event_key, json.dumps(record), record["sessionId"]),
            )
            return record, True
