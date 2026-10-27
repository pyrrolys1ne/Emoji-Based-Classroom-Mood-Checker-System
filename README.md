# 表情符号课堂情绪检查器系统

软件工程实践项目。学生通过 emoji 反馈课堂感受，教师查看课堂历史、实时看板与多维统计，管理员管理用户、安排课堂学生并导出数据；独立 AI 服务负责视频情绪分析。

当前为 **v0.1 协作框架**：管理端与学生端演示页面可运行，后端提供健康检查、接口契约和安全边界，数据库提供初始结构，AI 服务提供健康检查与推理扩展点。真实账号、RBAC、业务持久化、实时推送和模型推理尚未实现。

## 目录与分工

```text
apps/
  admin/                 管理端，组长负责；React + TypeScript + Vite
    src/views/           页面、布局、展示组件
    src/controllers/     页面状态与业务交互
    src/models/          统计、CSV 与领域规则
    src/repositories/    演示数据与 API 访问
  client/                学生端浏览器骨架；可由客户端负责人继续开发
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
infra/                   PostgreSQL 初始脚本与 Dockerfile
docs/                    架构、接口与团队协作说明
.github/workflows/       前后端构建与测试 CI
AGENTS.md                中文对话与需求记录
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

本地配置参考 `services/backend/.env.example`，复制为同目录 `.env` 后修改；配置文件路径独立于启动时所在目录。业务接口统一返回“尚未实现”，不会假装已写入数据库。未携带身份的受保护请求返回 401，任意占位令牌也不会获得用户权限。真实 JWT 与 RBAC 待后端负责人实现。

AI 服务单独启动：

```powershell
.\.venv\Scripts\python.exe -m pip install -r services/ai/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/ai --reload --host 127.0.0.1 --port 8001
```

访问 <http://127.0.0.1:8001/health>。该服务尚未加载模型、读取摄像头或上报记录。`pipeline.py` 是推理扩展点，`.env.example` 定义未来采样与上报配置约定。至少五种情绪枚举为初始 UI 分类，不意味着人脸模型可以直接、可靠地判断“专注”或“困惑”；正式映射须经实验验证。

macOS / Linux 使用 `.venv/bin/python` 替换 `.venv\Scripts\python.exe`。

## 数据库与容器

安装 Docker 后，可选择以下方式启动 PostgreSQL 与 Python 服务：

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

前端仍通过 npm 启动。数据库初始脚本为 `infra/database/001_initial.sql`，创建用户、课程、课堂会话、用户安排、情绪记录与审计日志。脚本只在空数据卷初始化时执行，后续变更请新增迁移脚本。未内置管理员账号；管理员初始化流程、密码加盐哈希和授权机制待实现。默认密码仅供本地开发，部署前更换。服务端口均绑定本机回环地址。

当前开发环境未安装 Docker，因此容器构建、数据库脚本实际执行尚未验证。

## 管理端接入真实 API

复制 `apps/admin/.env.example` 为同目录 `.env.local`，设置 `VITE_DATA_MODE=api`。开发服务器把 `/api` 请求代理到后端 8000 端口。重启 Vite 后生效。

目前 API 模式会显示后端未认证或未实现错误，这是预期行为。接入时先实现登录与服务端 RBAC，再在仓储层添加认证信息和明确的数据范围；不能通过前端角色判断替代服务端校验。默认演示模式没有真实账号认证。

## 验证

```powershell
npm run typecheck
npm run build
Push-Location services/backend
..\..\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

CI 在推送及拉取请求中执行前端构建和后端测试。数据库、摄像头与完整业务链路测试在相应功能实现后补充。

