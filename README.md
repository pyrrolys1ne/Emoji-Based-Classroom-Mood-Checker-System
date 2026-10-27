# 表情符号课堂情绪检查器系统

软件工程实践项目。学生通过 emoji 反馈课堂感受，教师查看课堂历史、实时看板与多维统计，管理员管理用户、安排课堂学生并导出数据；独立 AI 服务负责视频情绪分析。

管理端提供登录适配、教师视图、实时连接、日期时间统计、CSV 和 AI 控制页面；独立本地联调服务可验证“模拟采样 → 过滤 → 上报 → SQLite 保存 → 看板更新”。AI 服务包含模型适配、采样、持久化重试与启停。正式后端的接口状态见 API 文档；摄像头模式需要额外安装模型依赖。详见 [管理端与 AI 开发说明](docs/admin-ai.md)。

启动联调：首次执行 `.venv` 创建命令，并安装 `services/integration/requirements.txt` 与 `services/ai/requirements.txt` 中的依赖；之后运行 `npm run dev:integration`，打开 <http://127.0.0.1:5175>。合成账号 `admin` 或 `teacher`，密码均为 `integration-only`，仅供开发联调。

## 项目结构

图片表情分析可调用 DeepSeek `deepseek-flash`，无需安装本地模型。支持公开人像样本下载、无人脸对照与管理员分析页面，配置和命令见 [图片 API 说明](docs/image-api.md)。样本结果仅供测试，不写入课堂统计。

```text
apps/
  admin/                 管理端；React + TypeScript + Vite
    src/views/           页面、布局、展示组件
    src/controllers/     页面状态与业务交互
    src/models/          统计、CSV 与领域规则
    src/repositories/    演示数据与 API 访问
  client/                学生端浏览器界面
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
scripts/                 联调进程启动与关闭
infra/                   PostgreSQL 初始脚本与 Dockerfile
docs/                    架构、接口与团队协作说明
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
# 另开一个终端启动学生端演示
npm run dev:client
```

学生端位于 <http://127.0.0.1:5174>，可选择表情并查看本次页面会话的演示历史。两个演示端的数据不互通，均不代表真实用户数据。

## 启动后端与 AI 骨架

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r services/backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/backend --reload --host 127.0.0.1 --port 8000
```

- 后端存活检查：<http://127.0.0.1:8000/api/health>。
- 数据库就绪检查：<http://127.0.0.1:8000/api/ready>，数据库不可用时返回 503。
- Swagger 文档：<http://127.0.0.1:8000/docs>。
- OpenAPI：<http://127.0.0.1:8000/openapi.json>。

本地配置参考 `services/backend/.env.example`，复制为同目录 `.env` 后修改；配置文件路径独立于启动时所在目录。业务接口统一返回“尚未实现”，不会假装已写入数据库。未携带身份的受保护请求返回 401，任意占位令牌也不会获得用户权限。JWT 与 RBAC 的正式实现位于后端模块。

AI 服务单独启动：

```powershell
.\.venv\Scripts\python.exe -m pip install -r services/ai/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/ai --reload --host 127.0.0.1 --port 8001
```

访问 <http://127.0.0.1:8001/health>。服务默认不采集；控制接口需要独立 `AI_CONTROL_TOKEN`，上报需要 `AI_SERVICE_TOKEN`。服务自动读取 `services/ai/.env`，已有进程环境变量优先，联调脚本自动注入临时令牌。真实模型依赖位于 `requirements-model.txt`，基础联调无需安装。“专注”“困惑”仅作为手动反馈，AI 映射七种基本表情。模型与摄像头的兼容性应在目标运行环境验证。

macOS / Linux 使用 `.venv/bin/python` 替换 `.venv\Scripts\python.exe`。

## 数据库与容器

安装 Docker 后，可选择以下方式启动 PostgreSQL 与 Python 服务：

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

前端仍通过 npm 启动。数据库初始脚本为 `infra/database/001_initial.sql`，创建用户、课程、课堂会话、用户安排、情绪记录与审计日志。脚本只在空数据卷初始化时执行，后续变更请新增迁移脚本。未内置管理员账号；管理员初始化流程、密码加盐哈希和授权机制待实现。默认密码仅供本地开发，部署前更换。服务端口均绑定本机回环地址。

## 管理端接入真实 API

复制 `apps/admin/.env.example` 为同目录 `.env.local`，设置 `VITE_DATA_MODE=api`。开发服务器把 `/api` 请求代理到后端 8000 端口。重启 Vite 后生效。

API 模式已支持登录、会话恢复与认证请求。正式后端目前仍返回未实现错误，接入前需补齐契约与权限校验。独立联调环境提供合成账号与服务端权限范围，用于验证管理端与 AI 的接口。默认纯演示模式没有真实账号认证。

## 验证

```powershell
npm run typecheck
npm run test:admin
npm run build
Push-Location services/backend
..\..\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

CI 执行前端构建、管理端模型测试、后端、AI 与独立联调测试。完整测试指令见 `docs/admin-ai.md`。模型效果与部署兼容性应使用对应的运行环境评估。
