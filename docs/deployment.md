# 部署与恢复

本文介绍 Docker Compose 部署、升级与恢复；无需 Docker 的 Windows 本机安装、配置和进程启停见 [本地部署](local-deployment.md)。

正式运行使用 PostgreSQL、正式后端、独立 AI 服务，以及 API 模式构建的两个静态站点。`services/integration` 不参与部署。需要 Docker Engine 和支持 `service_completed_successfully`、`up --wait` 的 Compose v2。

## 配置与首次启动

以下命令从仓库根目录执行，示例使用 Bash；PowerShell 用 `Copy-Item` 替换 `cp`。

```bash
cp .env.example .env
# 编辑 .env：更换数据库密码，分别设置两个不同的随机 AI 令牌。
docker compose config --quiet
docker compose up --build -d --wait
docker compose exec backend python -m app.cli.create_admin_invite --expires-in-hours 24
```

命令生成一次性管理员邀请码，在管理端登录页通过“管理员注册”创建账号并登录。已有管理员可在“用户管理”生成新邀请码；普通注册只能创建学生或教师申请，审批、课程和课堂安排见 [账号认证](backend-auth.md) 与 [课堂管理](backend-classrooms.md)。不内置真实账号或课堂。

默认入口为管理端 `http://127.0.0.1:5173`、客户端 `http://127.0.0.1:5174`。两个 Nginx 站点提供生产静态文件，将 `/api/` 转发至正式后端，将 `/ws/dashboard` 转发并升级为 WebSocket。健康检查分别覆盖数据库、后端数据库连通性、AI 存活与静态首页；`/api/ready` 不证明迁移完整或模型已加载，迁移另由前置服务和验收保证。

| 配置                                                | 作用                                                                               |
| --------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD` | 数据库与独立强密码；密码在连接 URL 中使用，含保留字符时须按 URL 规则编码           |
| `MOOD_AI_SERVICE_TOKEN`                             | 后端入库认证，同步注入 AI 的 `AI_SERVICE_TOKEN`                                    |
| `MOOD_AI_CONTROL_TOKEN`                             | 后端控制代理认证，同步注入 AI 的 `AI_CONTROL_TOKEN`；与入库令牌不同                |
| `MOOD_CORS_ORIGINS`                                 | JSON 数组，精确列出浏览器实际访问的来源，包含协议和端口；同时校验 WebSocket Origin |
| `MOOD_ADMIN_PUBLIC_URL`                             | 留空时使用客户端当前主机的 5173 端口；设置显式入口后重建 client 镜像               |
| `MOOD_*_PORT`                                       | PostgreSQL、后端、AI、管理端、客户端的本地映射端口，见根 `.env.example`            |
| `MOOD_REALTIME_POLL_SECONDS`                        | 服务端重新检查实时身份和版本的间隔，默认 1 秒                                      |
| `MOOD_ALLOW_SIMULATED_AI`                           | 正式数据保持 `false`；系统验收仅在独立临时库中打开                                 |
| `DEEPSEEK_API_KEY`                                  | 可选，仅传入 AI 服务；空值不调用远程模型                                           |

Compose 内部固定使用 `http://backend:8000` 上报、`http://ai:8001` 控制，避免把宿主机回环地址当作服务地址。所有宿主机端口默认只绑定回环地址。同一局域网通过 IP 使用时，仅在独立 Compose 覆盖配置中调整 admin、client 的宿主机端口绑定，并同步加入实际 IP 的两个 Web 来源；`MOOD_ADMIN_PUBLIC_URL` 留空即可沿用访问主机。无需购买域名，不能将数据库和 AI 内部控制端口直接暴露到网络。跨不可信网络发布时配置 TLS 与入口代理，保持 Origin 原值、WebSocket 升级头及足够的读取超时；HTTPS 页面使用 `wss`。

## AI 数据与设备

`mood_ai_data` 卷保存匿名结构化待上报队列与单独下载的公开测试样本；重建 AI 容器不丢失队列，服务重启不自动采集。普通停止使用 `docker compose down`，保留数据卷；`down --volumes` 会删除数据库和队列，仅用于可丢弃的隔离环境。

基础 AI 镜像只安装基础依赖，支持健康检查、受控模拟和显式的公开样本远程分析。真实摄像头模式需要在目标主机安装对应 [模型或摄像头依赖](admin-ai.md)，或构建含这些依赖并映射设备的独立部署配置；当前 Compose 未映射摄像头，不能将基础镜像启动成功视为真实模型通过。远程摄像头仍需在界面明确允许发送，设置次数、时长和采样间隔；不自动打开设备。

容器下载公开样本：`docker compose exec ai python -m app.sample_cli download`。实际图片或摄像头推理需要有效服务端密钥和明确操作，见 [图片接口](image-api.md)、[摄像头实验](camera-api.md)。公开样本不写课堂，模型自评分不是准确率。

## 升级与备份

先停止采集并备份，再运行 `docker compose run --rm migrate`；迁移成功后执行 `docker compose up --build -d --wait`。迁移失败时停止升级并核对原因，不修改旧迁移文件、不清库绕过约束。迁移机制只向前升级，回退代码前须确认数据库兼容；不兼容时恢复到独立环境核对后再切换。

以下 Bash 命令将备份保存在被 Git 忽略的目录；文件含账号哈希和业务数据，应按目标环境的访问与保留策略管理。

```bash
mkdir -p .local/backups
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > .local/backups/mood.dump
docker compose stop ai
docker compose cp ai:/var/lib/mood-ai/outbox.sqlite .local/backups/ai-outbox.sqlite
docker compose start ai
```

数据库恢复使用相同 PostgreSQL 主版本的 `createdb` 和 `pg_restore --no-owner`，先恢复到独立空库，核对迁移版本、记录、用户、课堂、幂等回执和审计后再配置后端连接。恢复队列前停止 AI，保留 SQLite 文件归属与写权限，确认对应课堂和幂等回执也已恢复。不要把恢复测试直接指向在线数据库。

`npm run test:system -- --runtime compose` 会创建随机项目与独立卷，执行真实浏览器、服务重启和 AI 队列恢复，并使用容器内 PostgreSQL 客户端备份到独立新库，逐行比较核心数据。它不操作日常 Compose 项目，结束后删除本次测试卷。执行范围和未验证项见 [系统验收](system-acceptance.md)。
