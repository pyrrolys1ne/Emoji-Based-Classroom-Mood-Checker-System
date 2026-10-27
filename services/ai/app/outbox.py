import json
import sqlite3
from pathlib import Path
from uuid import uuid4


class Outbox:
    """只持久化待重试的匿名情绪结果，幂等键跨重启保持不变。"""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def put(self, payload: dict):
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT count(*) FROM outbox").fetchone()[0] >= 1000:
                raise RuntimeError("待上报队列已满，请先恢复后端连接")
            connection.execute(
                "INSERT INTO outbox VALUES (?, ?)", (str(uuid4()), json.dumps(payload))
            )

    def peek(self):
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT id, payload FROM outbox ORDER BY rowid LIMIT 1"
            ).fetchone()
            return (row[0], json.loads(row[1])) if row else None

    def remove(self, key):
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM outbox WHERE id = ?", (key,))

    def count(self):
        with sqlite3.connect(self.path) as connection:
            return connection.execute("SELECT count(*) FROM outbox").fetchone()[0]
