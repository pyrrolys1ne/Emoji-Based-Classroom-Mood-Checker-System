"""隔离正式后端、AI 服务和前端生产构建的系统验收，不使用联调替身。"""

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import SQLAlchemyError
from websockets.sync.client import connect
from websockets.exceptions import WebSocketException

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "synthetic-acceptance-password"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def until(check, message, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except httpx.TransportError:
            pass
        time.sleep(0.15)
    raise RuntimeError(message)


class Stack:
    def __init__(self, runtime, directory):
        self.runtime = runtime
        self.directory = directory
        self.processes = {}
        self.logs = []
        self.admin_engine = None
        self.database_name = None
        self.compose_started = False
        self.temporary = tempfile.TemporaryDirectory(prefix="runtime-", dir=directory)
        self.runtime_directory = Path(self.temporary.name)
        self.project = "mood-acceptance-" + uuid4().hex[:12]
        listeners = [socket.socket() for _ in range(5)]
        try:
            for listener in listeners:
                listener.bind(("127.0.0.1", 0))
            ports = [listener.getsockname()[1] for listener in listeners]
        finally:
            for listener in listeners:
                listener.close()
        self.ports = dict(zip(("backend", "ai", "admin", "client", "postgres"), ports))
        self.urls = {key: f"http://127.0.0.1:{port}" for key, port in self.ports.items()}
        self.env = {
            **os.environ,
            "MOOD_AI_SERVICE_TOKEN": secrets.token_hex(32),
            "MOOD_AI_CONTROL_TOKEN": secrets.token_hex(32),
            "MOOD_ALLOW_SIMULATED_AI": "true",
            "MOOD_AI_MIN_CONFIDENCE": "0.5",
            "MOOD_USER_SESSION_TTL_SECONDS": "28800",
            "MOOD_WS_TICKET_TTL_SECONDS": "30",
            "MOOD_MIGRATION_DIRECTORY": str(ROOT / "infra/database"),
            "MOOD_REALTIME_POLL_SECONDS": "0.2",
            "MOOD_CORS_ORIGINS": json.dumps([self.urls["admin"], self.urls["client"]]),
            "MOOD_AI_BASE_URL": self.urls["ai"],
            "MOOD_ADMIN_PUBLIC_URL": self.urls["admin"],
            "DEEPSEEK_API_KEY": "",
            "PYTHONIOENCODING": "utf-8",
        }
        self.env.update({f"MOOD_{key.upper()}_PORT": str(port) for key, port in self.ports.items()})

    def run(self, command, cwd=ROOT, env=None, input=None, timeout=120):
        with (self.directory / "commands.log").open("a", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=cwd, env=env or self.env, input=input,
                                    text=True, stdout=log, stderr=log, timeout=timeout)
        require(result.returncode == 0, "子进程失败，请查看 .local/acceptance/commands.log。")

    def compose(self, *args, timeout=180):
        self.run(["docker", "compose", "--env-file", str(self.directory / "compose.env"),
                  "-p", self.project, *args], timeout=timeout)

    def service_command(self, name):
        if name in {"backend", "ai"}:
            return [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                    "--port", str(self.ports[name]), "--no-access-log", "--log-level", "warning"]
        return ["node", str(ROOT / "node_modules/vite/bin/vite.js"), "preview", "--host",
                "127.0.0.1", "--port", str(self.ports[name]), "--strictPort"]

    def start_service(self, name):
        directory = ROOT / (f"services/{name}" if name in {"backend", "ai"} else f"apps/{name}")
        env = {**self.env, "PYTHONPATH": str(directory)}
        if name == "ai":
            env.update(AI_BACKEND_URL=self.urls["backend"],
                       AI_SERVICE_TOKEN=self.env["MOOD_AI_SERVICE_TOKEN"],
                       AI_CONTROL_TOKEN=self.env["MOOD_AI_CONTROL_TOKEN"],
                       AI_OUTBOX_PATH=str(self.runtime_directory / "ai/outbox.sqlite"),
                       AI_DATA_DIR=str(self.runtime_directory / "ai"))
        else:
            env.update(VITE_DATA_MODE="api", VITE_API_BASE_URL="/api", VITE_WS_URL="",
                       MOOD_API_TARGET=self.urls["backend"], VITE_API_PROXY_TARGET=self.urls["backend"])
        log = (self.directory / f"{name}.log").open("a", encoding="utf-8")
        self.logs.append(log)
        self.processes[name] = subprocess.Popen(self.service_command(name), cwd=directory, env=env,
                                                stdout=log, stderr=log)

    def stop_service(self, name):
        if self.runtime == "compose":
            self.compose("stop", "-t", "10", name)
        else:
            process = self.processes.pop(name)
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def restart_service(self, name):
        if self.runtime == "compose":
            self.compose("start", name)
        else:
            self.start_service(name)
        self.wait_service(name)

    def wait_service(self, name):
        path = {"backend": "/api/ready", "ai": "/health"}.get(name, "/")

        def ready():
            if name in self.processes:
                require(self.processes[name].poll() is None, f"{name} 启动时提前退出。")
            return httpx.get(self.urls[name] + path, timeout=1, trust_env=False).status_code == 200

        until(ready, f"{name} 就绪超时。", seconds=60)

    def start(self):
        if self.runtime == "compose":
            require(shutil.which("docker"), "容器验收需要 Docker Engine 和 Compose。")
            # 空 env 文件阻止读入项目 .env；随机项目名只操作本次创建的容器和卷。
            (self.directory / "compose.env").write_text("", encoding="utf-8")
            self.env.update(POSTGRES_DB="mood_acceptance", POSTGRES_USER="mood_acceptance",
                            POSTGRES_PASSWORD=secrets.token_hex(24))
            self.compose_started = True
            self.compose("up", "--build", "-d", "--wait", "--wait-timeout", "180", timeout=900)
        else:
            require(os.getenv("MOOD_TEST_DATABASE_URL"), "请设置可创建临时库的 MOOD_TEST_DATABASE_URL。")
            url = make_url(os.environ["MOOD_TEST_DATABASE_URL"])
            require(url.drivername == "postgresql+psycopg", "系统验收仅支持真实 PostgreSQL。")
            self.admin_engine = create_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
            name = "mood_acceptance_" + uuid4().hex
            with self.admin_engine.connect() as connection:
                connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
            self.database_name = name
            self.env["MOOD_DATABASE_URL"] = url.set(database=name).render_as_string(hide_password=False)
            self.run([sys.executable, "-m", "app.db.migrate"], ROOT / "services/backend")
            self.run([shutil.which("npm") or "npm", "run", "build"], env={
                **self.env, "VITE_DATA_MODE": "api", "VITE_API_BASE_URL": "/api", "VITE_WS_URL": "",
                "VITE_ADMIN_URL": self.urls["admin"],
            })
            for name in ("backend", "ai", "admin", "client"):
                self.start_service(name)
        for name in ("backend", "ai", "admin", "client"):
            self.wait_service(name)
        command = ["python" if self.runtime == "compose" else sys.executable, "-m",
                   "app.cli.bootstrap_admin", "--username", "acceptance-admin", "--email",
                   "acceptance-admin@example.edu", "--password-stdin"]
        if self.runtime == "compose":
            command = ["docker", "compose", "--env-file", str(self.directory / "compose.env"),
                       "-p", self.project, "exec", "-T", "backend", *command]
        self.run(command, ROOT if self.runtime == "compose" else ROOT / "services/backend", input=PASSWORD + "\n")

    def cleanup(self):
        try:
            for name in list(self.processes):
                self.stop_service(name)
            if self.compose_started:
                self.compose("down", "--volumes", "--remove-orphans")
        finally:
            for log in self.logs:
                log.close()
            if self.admin_engine:
                try:
                    if self.database_name:
                        with self.admin_engine.connect() as connection:
                            connection.exec_driver_sql(f'DROP DATABASE "{self.database_name}" WITH (FORCE)')
                finally:
                    self.admin_engine.dispose()
            self.temporary.cleanup()


def prepare(stack):
    with httpx.Client(base_url=stack.urls["backend"] + "/api", trust_env=False, timeout=15) as api:
        def request(method, path, **kwargs):
            response = api.request(method, path, **kwargs)
            require(response.status_code == 200, f"测试数据准备失败：{method} {path}")
            return response.json()["data"]

        admin = request("POST", "/auth/login", json={"username": "acceptance-admin", "password": PASSWORD})
        api.headers["Authorization"] = "Bearer " + admin["token"]
        for username, role in (("acceptance-teacher", "TEACHER"), ("other-teacher", "TEACHER"),
                               ("acceptance-student", "STUDENT"), ("other-student", "STUDENT")):
            request("POST", "/auth/register", json={"username": username, "email": username + "@example.edu",
                                                       "password": PASSWORD, "role": role})
        require(api.post("/auth/login", json={"username": "acceptance-teacher", "password": PASSWORD}).status_code == 403,
                "未审核教师不应获准登录。")
        require(api.post("/auth/register", json={"username": "self-admin", "email": "self-admin@example.edu",
                                                "password": PASSWORD, "role": "ADMIN"}).status_code == 422,
                "公开注册不应允许授予管理员。")
        for application in request("GET", "/admin/teacher-applications"):
            request("PUT", "/admin/teacher-applications/" + application["id"], json={"decision": "APPROVED"})
        users = {user["username"]: user for user in request("GET", "/admin/users")}
        now = datetime.now(timezone.utc)
        sessions = []
        for teacher, student in (("acceptance-teacher", "acceptance-student"), ("other-teacher", "other-student")):
            course = request("POST", "/admin/courses", json={"name": "验收课程-" + teacher,
                                                                 "teacherId": users[teacher]["id"]})
            classroom = request("POST", "/admin/sessions", json={"courseId": course["id"],
                "startsAt": (now - timedelta(minutes=5)).isoformat(),
                "endsAt": (now + timedelta(hours=1)).isoformat(), "room": "101", "className": "合成验收班"})
            request("POST", "/admin/sessions/" + classroom["id"] + "/schedule", json={"userIds": [users[student]["id"]]})
            sessions.append(classroom)
        return {"admin": admin, "users": users, "sessions": sessions}


def browser(stack, fixtures, phase):
    result = subprocess.run(["node", "scripts/system-browser.mjs"], cwd=ROOT, env={
        **stack.env, "MOOD_ACCEPTANCE_FIXTURES": json.dumps(fixtures),
        "MOOD_ACCEPTANCE_URLS": json.dumps(stack.urls), "MOOD_ACCEPTANCE_PHASE": phase,
    }, text=True, encoding="utf-8", capture_output=True, timeout=180)
    # 浏览器异常和追踪仅写本地忽略目录，不输出令牌或测试资料。
    (stack.directory / f"browser-{phase}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    require(result.returncode == 0, f"浏览器验收失败，请查看 .local/acceptance/browser-{phase}.log。")
    print(result.stdout.strip(), flush=True)


def persistence(stack, fixtures):
    headers = {"Authorization": "Bearer " + fixtures["admin"]["token"]}
    control = {"Authorization": "Bearer " + stack.env["MOOD_AI_CONTROL_TOKEN"]}
    with httpx.Client(trust_env=False, timeout=15) as client:
        def backend(path, method="GET", **kwargs):
            response = client.request(method, stack.urls["backend"] + "/api" + path, headers=headers, **kwargs)
            require(response.status_code == 200, "持久性验收的后端请求失败。")
            return response.json()["data"]

        def ai(path, method="GET", **kwargs):
            response = client.request(method, stack.urls["ai"] + "/control" + path, headers=control, **kwargs)
            require(response.status_code == 200, "持久性验收的 AI 控制请求失败。")
            return response.json()["data"]

        previous = backend("/emoji/history")
        ticket = backend("/auth/ws-ticket", "POST")["ticket"]
        config = {"sessionId": fixtures["sessions"][0]["id"], "mode": "simulation",
                  "sampleIntervalSeconds": 0.5, "confidenceThreshold": 0.75}
        stack.stop_service("backend")
        ai("/start", "POST", json=config)
        until(lambda: ai("/status")["pending"] > 0, "断网后未形成持久化上报队列。")
        ai("/stop", "POST")
        queued = ai("/status")["pending"]
        require(queued > 0, "断网时错误丢弃待上报结果。")
        stack.stop_service("ai")
        stack.restart_service("ai")
        require(ai("/status")["pending"] == queued, "AI 重启丢失待上报队列。")
        require(not ai("/status")["running"], "AI 重启后未经明确操作自动采集。")
        stack.restart_service("backend")
        require({record["id"] for record in previous} == {record["id"] for record in backend("/emoji/history")},
                "后端重启后记录发生变化。")
        with connect(stack.urls["backend"].replace("http:", "ws:") + "/ws/dashboard?ticket=" + ticket,
                     origin=stack.urls["admin"], open_timeout=10, proxy=None) as socket_client:
            snapshot = json.loads(socket_client.recv(timeout=5))
            require(snapshot["total"] == len(previous), "重启后的实时票据或快照错误。")
        backend("/admin/ai/start", "POST", json=config)
        until(lambda: ai("/status")["pending"] == 0 and ai("/status")["submitted"] >= queued,
              "重启后的队列未完成上报。")
        backend("/admin/ai/stop", "POST")
        after = backend("/emoji/history")
        require({record["id"] for record in previous} <= {record["id"] for record in after}, "重试后原记录丢失。")
        require(all(record["userId"] is None and record["simulated"] for record in after if record["source"] == "AI"),
                "模拟 AI 记录缺少匿名或模拟标记。")
        require(sum(record["source"] == "MANUAL" for record in after) == 13, "手动记录数量与幂等策略不一致。")
        print("通过：后端记录、会话和未消费票据重启持久性；AI 断网队列、重启保留与恢复上报。", flush=True)


def backup_restore(stack):
    """容器中的 PostgreSQL 客户端与服务端版本一致，恢复到独立新库核对。"""
    username = stack.env["POSTGRES_USER"]
    database = stack.env["POSTGRES_DB"]
    restored = "mood_acceptance_restored"
    dump = "/tmp/mood-acceptance.dump"
    stack.compose("exec", "-T", "db", "pg_dump", "-U", username, "-d", database, "-Fc", "-f", dump)
    stack.compose("exec", "-T", "db", "createdb", "-U", username, "-T", "template0", restored)
    stack.compose("exec", "-T", "db", "pg_restore", "-U", username, "-d", restored, "--no-owner", dump)
    url = URL.create("postgresql+psycopg", username=username, password=stack.env["POSTGRES_PASSWORD"],
                     host="127.0.0.1", port=stack.ports["postgres"], database=database)
    values = []
    for name in (database, restored):
        engine = create_engine(url.set(database=name), poolclass=NullPool, hide_parameters=True)
        try:
            with engine.connect() as connection:
                values.append({table: connection.execute(text(f'SELECT * FROM "{table}" ORDER BY 1')).all()
                               for table in ("schema_migration", "app_user", "user_session", "ws_ticket",
                                             "teacher_application", "course", "class_session", "schedule_user",
                                             "classroom_import", "emoji_record", "audit_log", "ai_ingestion")})
        finally:
            engine.dispose()
    require(values[0] == values[1], "备份恢复后的账号、课堂、记录、会话、审计或幂等回执不一致。")
    print("通过：PostgreSQL 自定义格式备份恢复到独立新库，逐行核对核心业务与迁移数据。", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("local", "compose"), default="local")
    args = parser.parse_args()
    directory = ROOT / ".local/acceptance"
    directory.mkdir(parents=True, exist_ok=True)
    # 同一个产物目录不允许并发运行，防止相互覆盖诊断结果。
    lock_path = directory / "running.lock"
    try:
        lock = lock_path.open("x")
    except FileExistsError:
        print("已有系统验收占用 .local/acceptance；请确认进程退出后再删除 running.lock。", file=sys.stderr)
        return 1
    stack = Stack(args.runtime, directory)
    report = {"runtime": args.runtime, "status": "failed", "realModel": "not_executed",
              "camera": "not_executed", "remoteInference": "not_executed",
              "backupRestore": "not_executed"}
    try:
        print("启动隔离系统验收：仅合成账号、临时数据库和明确标记的模拟 AI。", flush=True)
        stack.start()
        fixtures = prepare(stack)
        browser(stack, fixtures, "main")
        persistence(stack, fixtures)
        browser(stack, fixtures, "restore")
        if args.runtime == "compose":
            stack.compose("run", "--rm", "migrate")
            backup_restore(stack)
            report["backupRestore"] = "passed"
        else:
            stack.run([sys.executable, "-m", "app.db.migrate"], ROOT / "services/backend")
        report["status"] = "passed"
        print("系统验收通过；真实模型、摄像头、付费推理另行验收。", flush=True)
        return 0
    except (RuntimeError, subprocess.TimeoutExpired, OSError, SQLAlchemyError, ValueError, WebSocketException) as error:
        print(str(error) if isinstance(error, RuntimeError) else "验收进程异常或超时，请查看本地诊断文件。", file=sys.stderr)
        return 1
    finally:
        try:
            stack.cleanup()
        except Exception:
            report["status"] = "failed"
            print("测试资源清理失败，请核对独立测试项目或临时库，不操作日常环境。", file=sys.stderr)
            return 1
        finally:
            (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            lock.close()
            lock_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
