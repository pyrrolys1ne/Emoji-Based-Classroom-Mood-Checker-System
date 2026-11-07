# 本地部署（Windows PowerShell）

本文从仓库根目录启动 PostgreSQL、正式后端、独立 AI 服务及 API 模式的管理端、客户端，不使用 `services/integration`。适用于本机开发与实验；前端通过 Vite preview 提供构建产物和代理。需要对外长期提供服务时，使用 [容器部署与恢复](deployment.md) 中的 Nginx 入口方案。

## 1. 准备依赖

| 依赖                        | 用途                                                                                                            |
| --------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Node.js 22.12 以上，建议 24 | 安装依赖、构建及运行两个 Web 端                                                                                 |
| Python 3.13                 | 正式后端与 AI 服务                                                                                              |
| PostgreSQL 17               | 持久化业务数据；需有 `psql`、`pg_ctl`、`initdb`、`createuser`、`createdb`、`pg_dump`、`pg_restore` 等客户端工具 |

安装 PostgreSQL 时可以使用系统服务，也可以使用解压后的程序运行独立数据目录。PostgreSQL 程序、虚拟环境和依赖目录均不随仓库分发。

```powershell
node --version
python --version
npm ci
if (-not (Test-Path .venv/Scripts/python.exe)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r services/backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -r services/ai/requirements.txt
```

手动反馈、历史、统计和看板无需安装模型。需要 DeepSeek 摄像头实验时，再安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r services/ai/requirements-camera.txt
```

## 2. 准备 PostgreSQL

默认使用回环地址 `127.0.0.1:5432`。已有数据库或服务时先确认端口和账号，复用已有配置，不重复初始化或覆盖数据目录。

在当前终端设置 PostgreSQL 程序目录。可将程序加入 `PATH`，也可通过 `MOOD_PG_BIN` 环境变量指定安装目录下的 `bin`。以下同时支持仓库忽略目录中的便携程序布局：

```powershell
if ($env:MOOD_PG_BIN) {
    $pgBin = $env:MOOD_PG_BIN
} elseif (Test-Path .local/postgresql-17/pgsql/bin/pg_ctl.exe) {
    $pgBin = (Resolve-Path .local/postgresql-17/pgsql/bin).Path
} else {
    $pgBin = Split-Path (Get-Command pg_ctl.exe -ErrorAction Stop).Source
}
& "$pgBin/psql.exe" --version
```

如果已安装并启动 PostgreSQL 系统服务，跳过下列数据目录初始化与启动命令，直接创建业务账号和数据库。

使用独立数据目录的新环境，首次执行：

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
& "$pgBin/initdb.exe" -D .local/postgres-data -U postgres -W -A scram-sha-256 --locale=C --encoding=UTF8
& "$pgBin/pg_ctl.exe" -D .local/postgres-data -l .local/postgres.log -o "-h 127.0.0.1 -p 5432" -w start
```

`initdb -W` 交互设置数据库管理员密码；不要把密码写入命令行。已有 `.local/postgres-data` 时只执行启动命令。

首次创建业务账号 `mood` 和数据库 `mood`。以下使用数据库管理员 `postgres` 执行；`createuser --pwprompt` 设置业务账号密码，`-W` 要求输入数据库管理员密码：

```powershell
& "$pgBin/createuser.exe" -h 127.0.0.1 -p 5432 -U postgres -W --pwprompt --no-superuser --no-createdb --no-createrole mood
& "$pgBin/createdb.exe" -h 127.0.0.1 -p 5432 -U postgres -W --owner=mood mood
```

账号或数据库已存在时跳过对应创建命令，核对密码和所有权。业务账号不需要超级用户或创建数据库权限；隔离测试使用的账号另需创建数据库权限。

## 3. 配置服务与前端

仅在目标文件不存在时复制示例，保留已有配置：

```powershell
if (-not (Test-Path services/backend/.env)) { Copy-Item services/backend/.env.example services/backend/.env }
if (-not (Test-Path services/ai/.env)) { Copy-Item services/ai/.env.example services/ai/.env }
if (-not (Test-Path apps/admin/.env.local)) { Copy-Item apps/admin/.env.example apps/admin/.env.local }
if (-not (Test-Path apps/client/.env.local)) { Copy-Item apps/client/.env.example apps/client/.env.local }
```

用编辑器以 UTF-8 无 BOM 保存这些文件。将以下尖括号占位符替换为实际配置，不能原样使用。可用下列命令分别生成两个不同的随机 AI 令牌，只存入服务端配置：

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))"
```

`services/backend/.env` 至少配置：

```dotenv
MOOD_DATABASE_URL=postgresql+psycopg://mood:<URL编码后的业务账号密码>@127.0.0.1:5432/mood
MOOD_CORS_ORIGINS=["http://127.0.0.1:5173","http://127.0.0.1:5174"]
MOOD_AI_SERVICE_TOKEN=<随机入库令牌>
MOOD_AI_CONTROL_TOKEN=<另一个随机控制令牌>
MOOD_AI_BASE_URL=http://127.0.0.1:8001
MOOD_AI_MIN_CONFIDENCE=0.5
MOOD_ALLOW_SIMULATED_AI=false
```

数据库连接 URL 中的密码需进行 URL 编码，尤其是 `@`、`:`、`/`、`#`、`%` 等保留字符。用户名、端口、库名与实际环境保持一致。

`services/ai/.env` 至少配置：

```dotenv
AI_BACKEND_URL=http://127.0.0.1:8000
AI_SERVICE_TOKEN=<与后端 MOOD_AI_SERVICE_TOKEN 相同>
AI_CONTROL_TOKEN=<与后端 MOOD_AI_CONTROL_TOKEN 相同>
AI_OUTBOX_PATH=.local/ai-outbox.sqlite
DEEPSEEK_API_KEY=
```

只有需要真实图片或远程摄像头推理时才填写 `DEEPSEEK_API_KEY`；留空不影响手动反馈等业务。密钥不得放入前端或使用 `VITE_` 前缀。两个 AI 令牌必须互不相同。

`apps/admin/.env.local`：

```dotenv
VITE_DATA_MODE=api
VITE_API_BASE_URL=/api
MOOD_API_TARGET=http://127.0.0.1:8000
```

`apps/client/.env.local`：

```dotenv
VITE_DATA_MODE=api
VITE_API_BASE_URL=/api
VITE_API_PROXY_TARGET=http://127.0.0.1:8000
VITE_ADMIN_URL=
```

使用 `127.0.0.1` 访问两个站点；`localhost` 是不同的浏览器来源，若要使用需同步加入 `MOOD_CORS_ORIGINS`。进程环境变量优先于 `.env`，前端已有的 `.env.production` 等配置也可能影响构建；若仍显示演示模式或连接地址不符，检查并清除冲突配置后重新构建。

## 4. 迁移数据库并注册管理员

数据库启动、后端配置完成后执行：

```powershell
$env:PYTHONPATH = 'services/backend'
.\.venv\Scripts\python.exe -m app.db.migrate
.\.venv\Scripts\python.exe -m app.cli.create_admin_invite --expires-in-hours 24
```

迁移按顺序执行 `infra/database` 中的 SQL，包含 `008_admin_invitations.sql`；重复执行只检查并跳过已有版本，不清空数据。命令生成一个 24 小时有效的一次性邀请码。启动服务后，在管理端登录页选择“管理员注册”，填写用户名、邮箱、密码、确认密码及邀请码，成功后使用新账号登录。

已有管理员可在“用户管理 → 邀请管理员”生成邀请码，有效期 1 小时至 7 天。邀请码只在生成结果中显示，数据库仅存摘要；注册成功立即失效，过期或已使用均拒绝，账号冲突不会消费邀请码。无邀请码不能注册管理员，也不能将已有学生或教师账号通过注册提权。首次部署仍可选择 [命令行直接初始化管理员](backend-auth.md)，两种方式任选其一。

## 5. 构建并启动

先构建 API 模式的两个 Web 端：

```powershell
npm run build
```

分别在四个终端执行下列命令，工作目录均为仓库根目录。保留终端运行，按 `Ctrl+C` 停止对应进程。

后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/backend --host 127.0.0.1 --port 8000 --no-access-log
```

AI 服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/ai --host 127.0.0.1 --port 8001 --no-access-log
```

管理端：

```powershell
npm exec --workspace @mood/admin -- vite preview --host 127.0.0.1 --port 5173 --strictPort
```

客户端：

```powershell
npm exec --workspace @mood/client -- vite preview --host 127.0.0.1 --port 5174 --strictPort
```

管理端代理 `/api` 和 `/ws`，客户端代理 `/api`。Vite preview 用于本机实验，不能作为面向公网的生产 Web 服务器。需要热更新开发时，可改用 `npm run dev:admin`、`npm run dev:client`，仍需保留两端 `VITE_DATA_MODE=api`。

| 入口                 | 地址                              |
| -------------------- | --------------------------------- |
| 管理端、教师完整看板 | <http://127.0.0.1:5173>           |
| 学生端、教师基础页   | <http://127.0.0.1:5174>           |
| 正式后端就绪检查     | <http://127.0.0.1:8000/api/ready> |
| 后端接口文档         | <http://127.0.0.1:8000/docs>      |
| AI 存活检查          | <http://127.0.0.1:8001/health>    |

这些入口仅本机可访问，不自动设置防火墙、局域网访问或开机自启。电脑关机、睡眠或进程停止时无法提供服务，数据库文件仍保留。

### 局域网 IP 访问

交付客户端为浏览器 Web，不需要 Android 安装包或域名。同一局域网的设备可直接访问部署电脑的 IP。

1. 使用 `ipconfig` 查找当前联网网卡的 IPv4 地址。以下配置中的 `<本机局域网IP>` 替换为该地址，不使用虚拟机或回环网卡地址。
2. 在 `services/backend/.env` 的 `MOOD_CORS_ORIGINS` 中保留回环来源，并加入 `http://<本机局域网IP>:5173` 和 `http://<本机局域网IP>:5174`。它必须是合法 JSON 数组，协议、IP、端口需精确匹配，不能用 `*` 代替。
3. `apps/client/.env.local` 中令 `VITE_ADMIN_URL` 留空，客户端会自动使用当前访问主机的 5173 端口；`VITE_API_BASE_URL=/api` 和两个后端代理地址保持不变。重新构建前端并重启后端。
4. 将第 5 节两个 Web 启动命令的 `--host 127.0.0.1` 改为 `--host 0.0.0.0`。后端、AI 和 PostgreSQL 继续只监听 `127.0.0.1`，由 Web 入口代理业务请求与 WebSocket。
5. 按实际网络配置允许可信局域网设备访问 TCP 5173、5174 端口；在另一台设备的浏览器访问 `http://<本机局域网IP>:5174`，教师和管理员使用 5173 端口。核对登录、表情提交、教师“管理端”链接和实时连接。

IP 改变后同步更新来源列表并重启后端；未固定 IP 时不要把旧地址作为长期入口。本机访问 IP 成功不能代替另一台设备的网络验证，校园网或访客 Wi-Fi 也可能隔离设备互访。HTTP 仅适用于可信本地实验网络，跨不可信网络提供服务时配置加密入口；这不要求购买域名。

## 6. 检查完整业务流程

1. 检查后端 `/api/ready` 与 AI `/health` 均返回成功；凭邀请码完成管理员注册并登录，确认显示“API 模式”和“实时通道已连接”。已有账号直接登录。健康检查只证明服务连通，不能替代业务验证。
2. 在客户端分别注册学生与教师。教师审批前不能登录；管理员在“教师审批”批准后，教师才能使用所授课堂功能。
3. 管理员在“课程课堂”创建课程与课堂，指定已批准且启用的教师，填写课堂时间；在“课堂安排”加入学生。可把开始时间设为稍后，安排完成后再进入课堂时段。
4. 学生登录客户端，选择已安排课堂，在 `[startsAt, endsAt)` 内提交表情，确认保存成功并能刷新查看个人历史。未安排的学生不能提交。
5. 任课教师查看课堂历史，管理员查看实时看板、多维统计与情绪记录。同一记录应跨端一致，来源为 `MANUAL`；CSV 导出应包含对应记录。
6. 验证退出后需要重新登录，改密后旧会话失效。停止并重新启动后端、数据库，再登录核对账号、课堂与历史仍在。

需要自动化验证时，使用 [系统验收](system-acceptance.md) 的独立临时库流程。它使用合成账号及标记的模拟 AI，不向日常数据库写测试记录，也不自动开启摄像头或调用付费 API。正式环境保持 `MOOD_ALLOW_SIMULATED_AI=false`。

## 7. 可选 AI 实验

配置服务端密钥后，可以下载清单中的公开样本：

```powershell
$env:PYTHONPATH = 'services/ai'
.\.venv\Scripts\python.exe -m app.sample_cli download
```

管理员进入“AI 集成”，选择样本、勾选允许发送至 DeepSeek 后分析。公开样本结果不计入课堂记录，详见 [图片 API](image-api.md)。

摄像头实验另需安装摄像头依赖，在界面关联有效课堂、选择“本机摄像头 + DeepSeek API”、明确允许发送采样帧，并设置采样次数、间隔和时长上限后启动。服务重启不自动采集；原始帧仅在内存中处理，不落盘，入库及重试只保存匿名结构化结果。详见 [摄像头实验](camera-api.md)。模型自评分未经校准，不能作为准确率、心理状态或学习效果。

## 8. 日常启动、停止与数据保留

配置不变时，无需重新创建账号、数据库或管理员。启动已有 PostgreSQL 后，执行迁移检查，并启动第 5 节的四个进程。前端配置或代码变化后重新构建。

停止时先在管理端停止 AI 采集，再依次停止 Web 端、AI 服务和后端。独立数据目录的 PostgreSQL 使用以下命令正常关闭；`$pgBin` 按第 2 节设置：

```powershell
& "$pgBin/pg_ctl.exe" -D .local/postgres-data -m fast -w stop
```

安装为系统服务的 PostgreSQL 使用对应的服务管理方式启停。不要删除数据目录来解决端口、登录或迁移错误。

| 数据                                     | 默认存放位置                                                                       |
| ---------------------------------------- | ---------------------------------------------------------------------------------- |
| 用户、课程、课堂、名单、反馈、会话及审计 | PostgreSQL 数据目录；独立目录示例为 `.local/postgres-data`，系统服务按安装配置保存 |
| AI 匿名结构化待重试队列                  | `AI_OUTBOX_PATH`，本文为 `.local/ai-outbox.sqlite`                                 |
| 公开测试样本及分析报告                   | `.local/`，或 `AI_DATA_DIR` 指定目录                                               |
| 服务凭据与配置                           | `services/backend/.env`、`services/ai/.env`                                        |

上述运行数据、凭据和前端本地配置均不提交 Git。

数据库备份命令如下；输入业务账号密码，备份文件只写入本地忽略目录：

```powershell
New-Item -ItemType Directory -Force .local/backups | Out-Null
& "$pgBin/pg_dump.exe" -h 127.0.0.1 -p 5432 -U mood -W -d mood -Fc -f .local/backups/mood.dump
```

恢复时由数据库管理员创建一个独立空库，例如 `mood_restore`，指定业务账号为所有者，再使用相同 PostgreSQL 主版本的工具恢复：

```powershell
& "$pgBin/createdb.exe" -h 127.0.0.1 -p 5432 -U postgres -W --owner=mood mood_restore
& "$pgBin/pg_restore.exe" -h 127.0.0.1 -p 5432 -U mood -W -d mood_restore --no-owner .local/backups/mood.dump
```

核对迁移版本、账号、课堂和记录后再切换连接，不直接覆盖在线数据库。AI 队列单独备份：先停止 AI 服务，再复制 `AI_OUTBOX_PATH` 指定文件；恢复前确认对应课堂和幂等回执也已恢复。完整备份策略见 [部署与恢复](deployment.md)。

## 常见问题

| 现象                                  | 检查方法                                                                     |
| ------------------------------------- | ---------------------------------------------------------------------------- |
| `pg_ctl` 等命令找不到                 | 检查 PostgreSQL 安装及 `MOOD_PG_BIN`；便携程序不是仓库依赖                   |
| 5432、8000、8001、5173 或 5174 已占用 | 检查已有服务，复用对应实例或先正常停止，避免重复启动                         |
| `/api/ready` 返回 503                 | 检查 PostgreSQL 是否启动、账号密码、库名和连接 URL                           |
| 数据库就绪但业务接口报错              | 检查迁移是否完成；就绪接口不校验全部表结构                                   |
| 页面显示演示模式                      | 检查两个 Web 端的 `VITE_DATA_MODE=api`，重新构建并刷新页面                   |
| 实时连接被拒绝                        | 使用配置中的协议、主机与端口；检查 Origin、`/ws` 代理及短期一次性票据        |
| 教师不能登录或学生没有课堂            | 检查教师审批、账号启用状态及学生课堂安排                                     |
| 学生提交失败                          | 检查名单和课堂时段，不能把接口失败视为保存成功                               |
| AI 状态未连接或提示认证失败           | 检查 8001 端口、`MOOD_AI_BASE_URL` 及两组令牌对应关系                        |
| 真实图片或摄像头推理失败              | 检查服务端密钥、网络、提供方状态及摄像头依赖；保留真实错误，不用模拟结果替代 |
