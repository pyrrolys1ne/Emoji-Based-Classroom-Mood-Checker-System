# 表情符号课堂情绪检查器系统

软件工程实践项目。学生通过 emoji 反馈课堂感受，教师查看课堂历史、实时看板与多维统计，管理员管理用户、安排课堂学生并导出数据；独立 AI 服务负责视频情绪分析。

管理端提供登录适配、教师视图、实时连接、日期时间统计、CSV 和 AI 控制页面；独立本地联调服务可验证“采样 → 过滤 → 上报 → SQLite 保存 → 看板更新”。AI 服务包含模型适配、采样、持久化重试与启停。正式后端的接口状态见 API 文档；本地 DeepFace 摄像头模式需要额外安装模型依赖。详见 [管理端与 AI 开发说明](docs/admin-ai.md)。

启动联调：首次执行 `.venv` 创建命令，并安装 `services/integration/requirements.txt` 与 `services/ai/requirements.txt` 中的依赖；之后运行 `npm run dev:integration`，打开 <http://127.0.0.1:5175>。合成账号 `admin` 或 `teacher`，密码均为 `integration-only`，仅供开发联调。

本机摄像头可使用 DeepSeek API 做有次数与时长上限的采样实验，无需本地模型权重；只需安装 `services/ai/requirements-camera.txt`，详见 [摄像头 API 实验](docs/camera-api.md)。

图片表情分析可调用 DeepSeek `deepseek-flash`，无需安装本地模型。支持公开人像样本下载、无人脸对照与管理员分析页面，配置和命令见 [图片 API 说明](docs/image-api.md)。样本结果仅供测试，不写入课堂统计。

## 项目结构

```text
apps/
  admin/                 管理端；React + TypeScript + Vite
    src/views/           页面、布局、展示组件
    src/controllers/     页面状态与业务交互
    src/models/          统计、CSV 与领域规则
    src/repositories/    演示数据与 API 访问
  client/                学生端与教师基础页；React + TypeScript + Vite
packages/contracts/      前端共享类型与 emoji 枚举
services/
  backend/               FastAPI 后端
    app/api/             控制器与接口路由
    app/services/        业务服务
    app/repositories/    数据访问
    app/schemas/         请求、响应契约
    app/core/            配置、认证扩展点、统一错误处理
    tests/               接口与安全边界检查
  ai/                    独立 AI 服务及推理管线扩展点
  integration/           管理端与 AI 本地参考服务，非正式后端
scripts/                 联调进程管理与隔离系统验收
infra/                   PostgreSQL 初始脚本与 Dockerfile
docs/                    架构、接口、部署与验收说明
.github/workflows/       前后端构建与测试 CI
AGENTS.md                开发规范与技术约束
```

## 快速启动管理端

需要 Node.js 22.12 以上（建议 24），Python 3.13。以下命令均从仓库根目录执行。

```powershell
npm ci
npm run dev:admin
```

打开 <http://127.0.0.1:5173>。默认使用演示数据，不依赖数据库或后端。包含课堂概览、用户目录、情绪记录、课堂学生安排和多维统计页面；支持筛选、分页、CSV 导出和本地安排保存。刷新会重新生成当天演示数据，安排结果保存在浏览器本地存储。

```powershell
# 另开一个终端启动客户端
npm run dev:client
```

客户端位于 <http://127.0.0.1:5174>，提供学生账号、课堂选择、表情反馈、持久演示历史、改密和退出，以及教师课堂历史与基础统计。默认演示模式有明确标识，可直接体验学生或教师；API 模式使用独立的真实接口适配，不会把接口失败显示为演示成功。两个演示端的数据不互通。配置、演示账号、架构和测试命令见 [客户端运行与维护](docs/client-development.md)，接口依赖见 [客户端对接约定](docs/client-integration.md)。正式后端账号、教师审批、课程课堂管理、学生安排、手动反馈、授权历史、全量统计和服务端 CSV 导出已实现。

## 启动后端与 AI 服务

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r services/backend/requirements-dev.txt
$env:PYTHONPATH = 'services/backend'
.\.venv\Scripts\python.exe -m app.db.migrate
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/backend --reload --host 127.0.0.1 --port 8000
```

- 后端存活检查：<http://127.0.0.1:8000/api/health>。
- 数据库就绪检查：<http://127.0.0.1:8000/api/ready>，数据库不可用时返回 503。
- Swagger 文档：<http://127.0.0.1:8000/docs>。
- OpenAPI：<http://127.0.0.1:8000/openapi.json>。

本地配置参考 `services/backend/.env.example`，复制为同目录 `.env` 后修改；配置文件路径独立于启动时所在目录。后端已实现注册、登录、本人信息、改密、注销、管理员用户目录、教师审批、课程课堂管理、学生资料、安排名单、手动反馈、授权历史查询和匿名 AI 入库。密码使用 Argon2id 加盐哈希，会话、反馈和审计持久化至 PostgreSQL。未携带有效身份的受保护请求返回 401，无所需角色返回 403。基础与多维统计、CSV 导出已接入全量记录，实时票据、WebSocket 刷新通知、授权看板和管理员 AI 控制代理已接通。

首个管理员通过受控命令初始化，终端隐藏读取并确认密码：

```powershell
.\.venv\Scripts\python.exe -m app.cli.bootstrap_admin --username admin --email admin@example.edu
```

公开注册不能创建管理员；教师申请审核批准后才能登录。已有管理员时初始化命令拒绝重复创建。多设备可同时登录，退出只撤销当前会话，改密撤销全部会话。命令、接口与权限说明见 [账号认证与教师审批](docs/backend-auth.md)。

管理员可通过管理接口创建课程、指定课堂任课教师并安排学生，也可使用受控初始化命令整批导入：

```powershell
.\.venv\Scripts\python.exe -m app.cli.import_classrooms --username admin --file docs/examples/classrooms.json
```

示例仅使用合成账号引用，运行前需要已有学生及已审核教师，并调整时间和批次编号；密码由终端隐藏读取，整批失败回滚，重复批次明确拒绝。教师只查询所授课堂，学生只查询被安排课堂及本人名单信息。接口和文件格式见 [课程课堂与学生安排](docs/backend-classrooms.md)。

学生在服务端课堂时段 `[startsAt,endsAt)` 内提交手动反馈；同一操作的重试复用 `Idempotency-Key`，主动再次反馈使用新键。学生查看本人手动历史，教师查看所授课堂历史；移出名单不删除既有反馈。接口示例、筛选和错误码见 [手动反馈与历史](docs/backend-feedback.md)。健康接口的 stage 为 `realtime-ai-control`。

AI 服务单独启动：

```powershell
.\.venv\Scripts\python.exe -m pip install -r services/ai/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/ai --reload --host 127.0.0.1 --port 8001
```

访问 <http://127.0.0.1:8001/health>。服务默认不采集；控制接口需要独立 `AI_CONTROL_TOKEN`，上报需要 `AI_SERVICE_TOKEN`。服务自动读取 `services/ai/.env`，已有进程环境变量优先，联调脚本自动注入临时令牌。真实模型依赖位于 `requirements-model.txt`，基础联调无需安装。“专注”“困惑”仅作为手动反馈，AI 映射七种基本表情。模型与摄像头的兼容性应在目标运行环境验证。

正式后端已接入匿名 AI 结构化上报。配置 `AI_BACKEND_URL` 指向正式后端，并使 `AI_SERVICE_TOKEN` 与后端 `MOOD_AI_SERVICE_TOKEN` 一致；控制令牌单独配置。采样须发生在课堂时段内，支持课后补传，低分过滤与重复上报均返回明确回执。模拟输入仅用于隔离开发数据库，正式默认拒绝；运行配置和错误处理见 [匿名 AI 入库](docs/backend-ai-ingestion.md)。

macOS / Linux 使用 `.venv/bin/python` 替换 `.venv\Scripts\python.exe`。

统计默认只含手动反馈，可显式选择 AI 或全部来源；教师只统计所授课堂，CSV 仅管理员可下载。正式管理端的情绪分布、时间趋势和课程班级汇总来自同一服务端响应；表格分页不截断导出。接口和 CSV 格式见 [全量统计与 CSV 导出](docs/backend-statistics.md)。

实时连接先以登录态换取 30 秒内有效的一次性票据，来源须精确匹配 `MOOD_CORS_ORIGINS`，退出后撤销对应访问。正式管理端默认 `/ws/dashboard`，开发代理已支持 WebSocket；部署代理需转发该路径的连接升级。AI 控制需要后端 `MOOD_AI_CONTROL_TOKEN` 与 AI 服务 `AI_CONTROL_TOKEN` 一致，真实采集仅由明确启动操作触发，远程模式需单独允许发送帧并限制采样次数和时长。协议、配置和未知结果处理见 [实时看板与 AI 控制](docs/backend-realtime-ai.md)。

## 数据库与容器

安装 Docker 后，可选择以下方式启动 PostgreSQL 与 Python 服务：

```powershell
Copy-Item .env.example .env
docker compose up --build -d --wait
```

Compose 同时构建 API 模式的管理端和客户端，由 Nginx 在 5173、5174 端口提供静态文件及 `/api/`、`/ws/dashboard` 代理。`migrate` 服务在 PostgreSQL 就绪后按顺序执行 `infra/database/001` 至 `007`，成功后启动后端；已有数据卷使用同一迁移入口。AI 的内部地址和独立令牌与后端同步，匿名重试队列保存到 `mood_ai_data` 卷，重启不自动采集。镜像不包含真实模型依赖或摄像头映射。

迁移记录版本和校验和，结构与升级见 [后端数据库说明](docs/backend-database.md)。不内置管理员账号；执行 `docker compose exec backend python -m app.cli.bootstrap_admin --username admin --email admin@example.edu` 受控创建。默认数据库密码仅供本地开发，启动前更换并配置两个不同的随机 AI 令牌。端口只绑定回环地址，域名、TLS、来源配置、升级与备份恢复见 [部署说明](docs/deployment.md)。普通停止保留数据卷，不要在需要保留数据的环境执行 `down --volumes`。

## 管理端接入真实 API

复制 `apps/admin/.env.example` 为同目录 `.env.local`，设置 `VITE_DATA_MODE=api`。开发服务器把 `/api` 请求代理到后端 8000 端口。重启 Vite 后生效。

API 模式支持登录、会话恢复、课堂选择、手动反馈与个人历史，可连接正式后端使用真实账号。教师需先获管理员批准，课堂、名单和历史按角色返回真实数据；教师基础统计支持按手动、AI、全部来源切换；正式管理端使用服务端多维统计和 CSV 下载，WebSocket 通知变化后自动刷新，管理员可启停独立 AI 服务并查询公开样本状态。独立联调环境继续提供合成账号与隔离数据，用于验证管理端与 AI 的完整参考接口。默认纯演示模式没有真实账号认证。

## 验证

```powershell
npm run typecheck
npm run test:admin
npm run build
Push-Location services/backend
..\..\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

设置具备创建数据库权限的 `MOOD_TEST_DATABASE_URL` 后，运行 `npm run test:system` 可验证两个生产构建、正式后端、真实 PostgreSQL 与独立 AI 的完整链路；使用独立临时库、随机令牌及明确标记的模拟输入，不使用参考联调替身。Docker 环境运行 `npm run test:system -- --runtime compose`，另验证 Nginx 代理、持久卷和备份恢复。

CI 执行类型与构建、前后端业务测试、AI 与联调测试、客户端浏览器兼容检查，以及真实数据库和容器系统验收。运行前提、覆盖和未执行的真实模型、摄像头、远程推理及目标主机项目见 [系统验收](docs/system-acceptance.md)。
