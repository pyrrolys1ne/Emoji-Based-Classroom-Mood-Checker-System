# 表情符号课堂情绪检查器系统

软件工程实践项目。学生通过表情符号反馈课堂感受，教师查看所授课堂的历史、实时看板与统计，管理员审批教师、管理课程课堂、安排学生并导出数据；独立 AI 服务支持摄像头表情分析及匿名结构化上报。

系统由 React + TypeScript Web 端、FastAPI 正式后端、PostgreSQL 数据库和独立 Python AI 服务组成。账号认证、课堂授权、手动反馈、全量统计、CSV 导出、WebSocket 实时通知和 AI 控制均通过正式后端提供。

## 运行方式

| 方式           | 数据与用途                                          | 说明                                                    |
| -------------- | --------------------------------------------------- | ------------------------------------------------------- |
| 本地完整部署   | 正式后端、PostgreSQL、AI 服务、两个 API 模式 Web 端 | [Windows PowerShell 部署步骤](docs/local-deployment.md) |
| Docker Compose | PostgreSQL、迁移、后端、AI、Nginx 静态站点及代理    | [容器部署、升级与恢复](docs/deployment.md)              |
| 前端演示       | 浏览器本地演示数据，两个 Web 端数据不互通           | 用于页面体验，不依赖后端                                |
| 独立联调       | 合成账号、SQLite、模拟输入及 AI 控制                | 只供开发，不作为正式部署                                |

## 本地完整部署

需要 Node.js 22.12 以上（建议 24）、Python 3.13 和 PostgreSQL 17。以下命令均在仓库根目录执行。首次部署按 [本地部署说明](docs/local-deployment.md) 完成 PostgreSQL 账号、数据库及环境配置，再运行迁移和服务。

安装依赖：

```powershell
npm ci
if (-not (Test-Path .venv/Scripts/python.exe)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r services/backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -r services/ai/requirements.txt
```

配置文件及关键字段：

| 文件                     | 配置                                                    |
| ------------------------ | ------------------------------------------------------- |
| `services/backend/.env`  | PostgreSQL 连接、浏览器来源、独立 AI 入库令牌及控制令牌 |
| `services/ai/.env`       | 后端地址、对应的两组 AI 令牌、可选 DeepSeek 密钥        |
| `apps/admin/.env.local`  | `VITE_DATA_MODE=api`、后端代理地址                      |
| `apps/client/.env.local` | `VITE_DATA_MODE=api`、后端代理地址和管理端链接          |

从对应 `.env.example` 创建配置，保留已有文件；密钥仅存服务端。后端 `MOOD_AI_SERVICE_TOKEN` 对应 AI 的 `AI_SERVICE_TOKEN`，后端 `MOOD_AI_CONTROL_TOKEN` 对应 AI 的 `AI_CONTROL_TOKEN`，两组令牌必须不同。正式数据保持 `MOOD_ALLOW_SIMULATED_AI=false`。

数据库启动并完成配置后，首次迁移、创建管理员和构建：

```powershell
$env:PYTHONPATH = 'services/backend'
.\.venv\Scripts\python.exe -m app.db.migrate
.\.venv\Scripts\python.exe -m app.cli.create_admin_invite --expires-in-hours 24
npm run build
```

命令生成一次性管理员邀请码。启动管理端后，在登录页选择“管理员注册”，填写用户名、邮箱、密码及邀请码；成功后回到登录页。已有管理员可在“用户管理 → 邀请管理员”生成新邀请码，有效期 1—168 小时，使用后失效。普通学生／教师注册不能自行选择管理员角色；教师需审核批准后才能登录。无默认管理员密码，日常启动不重复注册账号或生成邀请码。命令行直接初始化首个管理员的方式仍保留，见 [账号认证](docs/backend-auth.md)。

分别在四个终端启动，工作目录均为仓库根目录：

```powershell
# 终端 1：正式后端
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/backend --host 127.0.0.1 --port 8000 --no-access-log
```

```powershell
# 终端 2：独立 AI 服务，启动后不自动采集
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/ai --host 127.0.0.1 --port 8001 --no-access-log
```

```powershell
# 终端 3：管理端构建预览
npm exec --workspace @mood/admin -- vite preview --host 127.0.0.1 --port 5173 --strictPort
```

```powershell
# 终端 4：客户端构建预览
npm exec --workspace @mood/client -- vite preview --host 127.0.0.1 --port 5174 --strictPort
```

| 入口                 | 地址                              |
| -------------------- | --------------------------------- |
| 管理端、教师完整看板 | <http://127.0.0.1:5173>           |
| 学生端、教师基础页   | <http://127.0.0.1:5174>           |
| 后端就绪检查         | <http://127.0.0.1:8000/api/ready> |
| 后端接口文档         | <http://127.0.0.1:8000/docs>      |
| AI 存活检查          | <http://127.0.0.1:8001/health>    |

本地前端提供 `/api` 代理，管理端另代理 `/ws`。Vite preview 适用于本机实验，对外部署使用 Nginx。服务只绑定回环地址，不自动配置开机自启。停止前先关闭 AI 采集，再按 `Ctrl+C` 结束各终端进程；PostgreSQL 正常关闭后数据保留，重启电脑后需重新启动服务。数据库启停、数据目录、备份恢复和常见问题见 [本地部署说明](docs/local-deployment.md)。

客户端使用浏览器，无需安装 Android 应用或购买域名。同一局域网可通过 `http://<本机局域网IP>:5173`、`http://<本机局域网IP>:5174` 访问；按 [局域网 IP 配置](docs/local-deployment.md#局域网-ip-访问) 调整 Web 监听、来源和防火墙。数据库、后端及 AI 内部端口仍只在本机访问。

首次业务检查顺序：客户端注册学生和教师 → 管理端批准教师 → 创建课程课堂 → 安排学生 → 学生在课堂时段内提交表情 → 教师查询历史 → 管理员核对实时看板、统计和 CSV。界面应显示“API 模式”，完整步骤和独立验收命令见 [本地流程检查](docs/local-deployment.md#6-检查完整业务流程)。

## Docker Compose 部署

安装 Docker Engine 与 Compose v2 后，首次创建根目录 `.env`，更换数据库密码并配置两个不同的随机 AI 令牌，再执行：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 编辑 .env 完成配置后启动。
docker compose config --quiet
docker compose up --build -d --wait
docker compose exec backend python -m app.cli.create_admin_invite --expires-in-hours 24
```

Compose 使用 PostgreSQL 持久卷，先执行数据库迁移，再启动后端、AI 和两个 API 模式的 Nginx 站点。管理端和客户端仍使用 5173、5174 端口。镜像不包含真实模型依赖或摄像头映射。

凭生成的邀请码在管理端注册后登录。停止使用 `docker compose down`，保留数据库及 AI 队列卷；`down --volumes` 会删除数据。IP 入口、来源范围、升级、备份与恢复见 [部署说明](docs/deployment.md)。不要同时启动占用相同端口的本地进程和容器。

## AI 图片与摄像头

- DeepSeek `deepseek-flash` 支持公开样本识图及有次数、时长上限的摄像头实验，无需安装本地模型权重。密钥存于服务端，配置见 [图片 API](docs/image-api.md)。
- 摄像头另需安装 `services/ai/requirements-camera.txt`，由管理员明确启动；远程模式需单独允许发送采样帧。参数、设备和停止规则见 [摄像头实验](docs/camera-api.md)。
- 本地 DeepFace 模式另需 `services/ai/requirements-model.txt` 及模型权重，兼容性须在目标环境验证，见 [管理端与 AI 说明](docs/admin-ai.md)。

公开样本不写入课堂统计；真实采集默认匿名，不保存原始视频帧、人脸图像或特征。模型自评分未经校准，不代表准确率、心理状态或学习效果。“专注”“困惑”只作为手动反馈，不由表情模型推断。上报失败的匿名结构化结果保存在本地队列中，使用稳定幂等键重试。

## 演示与独立联调

仅体验前端页面时，不创建 `.env.local` 或将两端 `VITE_DATA_MODE` 设为 `demo`，分别运行 `npm run dev:admin`、`npm run dev:client`。演示模式有明确标识，数据不与正式后端互通；开发服务在配置变化后需重启。

独立联调需要安装 `services/integration/requirements.txt` 和 `services/ai/requirements.txt`，运行 `npm run dev:integration`，访问 <http://127.0.0.1:5175>。合成账号 `admin`、`teacher` 的密码均为 `integration-only`，仅供隔离联调，不能用于正式后端登录。

## 项目结构

```text
apps/admin/              管理端、教师看板；MVC 职责划分
apps/client/             学生端、教师基础页
packages/contracts/      共享类型、情绪枚举及接口契约
services/backend/        FastAPI 正式后端；Controller、Service、Repository 分层
services/ai/             独立 AI 服务、采样、推理适配及持久化重试
services/integration/    合成账号与 SQLite 参考联调服务
scripts/                 联调与隔离系统验收
infra/                   PostgreSQL 迁移、Dockerfile 及 Nginx 配置
docs/                    架构、接口、部署与验收说明
AGENTS.md                项目开发规范
```

## 验证

```powershell
npm run typecheck
npm run test:admin
npm run test:client
npm run build
.\.venv\Scripts\python.exe -m pytest services/backend/tests -q
.\.venv\Scripts\python.exe -m pytest services/ai/tests -q
```

后端真实 PostgreSQL 测试需要设置 `MOOD_TEST_DATABASE_URL`，测试账号须有创建数据库权限；未配置时相关测试会跳过，不能据此认定数据库验证通过。测试创建并清理独立临时库，不清空连接地址指向的数据库。

安装验收浏览器后执行完整链路验证：

```powershell
npx playwright install chromium
# 先设置指向独立测试环境的 MOOD_TEST_DATABASE_URL。
npm run test:system
```

系统验收使用正式后端、真实 PostgreSQL、两个前端构建和独立 AI 服务；只使用合成账号、临时数据库及明确标记的模拟 AI，不自动采集或调用付费 API。Docker 环境运行 `npm run test:system -- --runtime compose`，另验证 Nginx、持久卷和备份恢复。验证范围见 [系统验收](docs/system-acceptance.md)。

## 功能与接口文档

接收环境的完整测试清单、摄像头预演及 5～8 分钟录制脚本见 [交接说明](docs/handover.md)，已有验证结果与限制见 [项目验证报告](docs/project-verification.md)。

| 内容               | 文档                                                                             |
| ------------------ | -------------------------------------------------------------------------------- |
| 管理操作入口       | [教师审批、课程课堂与学生资料](docs/admin-management.md)                         |
| 数据库结构与迁移   | [后端数据库](docs/backend-database.md)                                           |
| 账号与角色         | [认证与教师审批](docs/backend-auth.md)                                           |
| 课程、课堂与名单   | [课堂管理](docs/backend-classrooms.md)                                           |
| 手动反馈与授权历史 | [反馈与历史](docs/backend-feedback.md)                                           |
| 统计与导出         | [全量统计与 CSV](docs/backend-statistics.md)                                     |
| 实时连接与 AI 控制 | [实时看板与 AI 控制](docs/backend-realtime-ai.md)                                |
| AI 上报与幂等      | [匿名 AI 入库](docs/backend-ai-ingestion.md)                                     |
| 客户端配置与接口   | [运行与维护](docs/client-development.md)、[对接约定](docs/client-integration.md) |
