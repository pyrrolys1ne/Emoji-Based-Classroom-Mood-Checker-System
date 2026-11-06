# 后端交付与联调说明

正式后端位于 `services/backend`，使用 FastAPI、SQLAlchemy 和 PostgreSQL，按 Controller、Service、Repository 分层。已实现账号认证、教师审批、课程课堂、学生资料与安排、手动反馈、授权历史、匿名 AI 入库、全量统计、CSV、实时授权及管理员 AI 控制代理。

当前接口契约为 v0.12，数据库迁移为 001—007。本文提供后端交付物与接入要求，逐项验证见 [后端联调验收清单](backend-acceptance.md)。`services/integration` 使用合成账号与 SQLite，只用于独立开发联调，不作为正式后端或正式账号来源。

## 交付物索引

| 交付物         | 入口与内容                                                                                                              |
| -------------- | ----------------------------------------------------------------------------------------------------------------------- |
| 接口总览       | [API 契约](api-contract.md)；运行后访问 `/docs`、`/openapi.json`                                                        |
| 账号与授权     | [账号认证与教师审批](backend-auth.md)：注册、登录、会话、改密、注销、受控管理员初始化                                   |
| 课程课堂       | [课堂与学生安排](backend-classrooms.md)：实际任课教师、学生资料、名单和受控批量初始化                                   |
| 手动记录       | [反馈与历史](backend-feedback.md)：课堂时段、稳定幂等键、授权查询与摘要                                                 |
| AI 上报        | [匿名 AI 入库](backend-ai-ingestion.md)：独立令牌、过滤、幂等回执与补传                                                 |
| 统计与文件     | [统计与 CSV](backend-statistics.md)：来源、全量聚合、时间桶、分组与安全导出                                             |
| 实时与 AI 控制 | [实时看板与代理](backend-realtime-ai.md)：一次性票据、WebSocket、管理员控制及未知结果                                   |
| 数据结构       | [数据库说明](backend-database.md)；`infra/database/001` 至 `007`，包含版本校验与升级约束                                |
| 请求与响应模型 | `services/backend/app/schemas/`、`packages/contracts/src/`；字段或枚举调整须同步调用方                                  |
| 配置示例       | `services/backend/.env.example`；真实密码和令牌不进入仓库                                                               |
| 自动化验证     | `services/backend/tests/`、`scripts/test_system.py`、`scripts/system-browser.mjs`；[系统验收说明](system-acceptance.md) |

## 角色与数据范围

| 能力                                             | 学生               | 教师             | 管理员       | AI 服务身份    |
| ------------------------------------------------ | ------------------ | ---------------- | ------------ | -------------- |
| 本人信息、改密、注销                             | 本人               | 本人             | 本人         | 禁止           |
| 课堂查询                                         | 当前被安排课堂     | 实际任课课堂     | 全部         | 禁止           |
| 提交手动反馈                                     | 名单内且在课堂时段 | 禁止             | 禁止         | 禁止           |
| 历史记录                                         | 本人 MANUAL 历史   | 实际任课课堂历史 | 全部授权记录 | 禁止           |
| 统计、看板与实时票据                             | 禁止               | 实际任课课堂     | 全部授权记录 | 禁止           |
| 用户目录、教师审批、课程课堂写入、学生资料与安排 | 禁止               | 禁止             | 允许         | 禁止           |
| CSV 与 AI 控制代理                               | 禁止               | 禁止             | 允许         | 禁止           |
| 结构化 AI 入库                                   | 禁止               | 禁止             | 禁止         | 仅独立入库令牌 |

公开注册只接受 STUDENT 或 TEACHER；教师申请获批后才能登录。管理员由受控 CLI 初始化，不提供公开提权接口。课程默认教师变化不转移已有课堂权限；名单移除不删除既有历史，学生仍可查询本人已提交的记录。AI 记录不归属个人，userId 和 student 为 null。

## 本地接入前提

准备可连接的 PostgreSQL、Python 环境，并安装 `services/backend/requirements-dev.txt`；运行完整测试还需 `services/ai/requirements.txt`。复制后端 `.env.example` 为同目录 `.env`，设置连接及服务端配置。以下命令从仓库根目录执行，使用 Bash；PowerShell 写法见各接口专题文档。

```bash
PYTHONPATH=services/backend .venv/bin/python -m app.db.migrate
PYTHONPATH=services/backend .venv/bin/python -m app.cli.bootstrap_admin --username admin --email admin@example.edu
.venv/bin/python -m uvicorn app.main:app --app-dir services/backend --host 127.0.0.1 --port 8000
```

管理员密码由终端隐藏读取；已有管理员时不重复初始化。随后通过注册、审批、课程课堂和名单接口准备合成联调数据，也可用 `app.cli.import_classrooms` 导入已有账号引用，格式见 `docs/examples/classrooms.json`。实际账号、密码与令牌不写入交付文档。联调课堂必须使用真实数据库返回的 UUID，并设置覆盖当前测试时间的时段。

`GET /api/health` 表示应用存活，`GET /api/ready` 只检查数据库连通性；成功响应不证明迁移、业务、模型或设备全部可用。数据库迁移必须单独执行并确认成功。

### 后端配置核对

| 配置                                                                                                                   | 接入要求                                                                         |
| ---------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `MOOD_DATABASE_URL`                                                                                                    | 使用 `postgresql+psycopg`；密码中保留字符按 URL 规则编码，正式与测试数据隔离     |
| `MOOD_DATABASE_CONNECT_TIMEOUT`、`MOOD_DATABASE_POOL_SIZE`、`MOOD_DATABASE_MAX_OVERFLOW`、`MOOD_DATABASE_POOL_TIMEOUT` | 分别控制连接超时、常驻池、溢出连接和池等待；范围见数据库说明                     |
| `MOOD_CORS_ORIGINS`                                                                                                    | JSON 数组，精确匹配页面来源的协议、主机与端口；同时用于 WebSocket Origin 校验    |
| `MOOD_USER_SESSION_TTL_SECONDS`、`MOOD_WS_TICKET_TTL_SECONDS`                                                          | 默认 28800 秒与 30 秒；票据不能晚于用户会话过期                                  |
| `MOOD_REALTIME_POLL_SECONDS`                                                                                           | 默认 1 秒，范围 0.1—5 秒；决定实时连接重新核对授权的间隔                         |
| `MOOD_AI_SERVICE_TOKEN`                                                                                                | 与 AI 的 `AI_SERVICE_TOKEN` 一致，仅供结构化入库                                 |
| `MOOD_AI_CONTROL_TOKEN`                                                                                                | 与 AI 的 `AI_CONTROL_TOKEN` 一致；必须与入库令牌不同，两者均不能使用 `usr_` 前缀 |
| `MOOD_AI_BASE_URL`                                                                                                     | 后端可访问的 AI 服务地址，默认 `http://127.0.0.1:8001`；浏览器不直接持有控制令牌 |
| `MOOD_AI_MIN_CONFIDENCE`                                                                                               | 默认 0.5，有限数值且在 0—1 内；低于阈值返回过滤回执                              |
| `MOOD_ALLOW_SIMULATED_AI`                                                                                              | 默认 false；只在独立测试库显式开启，记录始终保留 simulated 标记                  |

AI 上报还需将 `AI_BACKEND_URL` 指向正式后端。`DEEPSEEK_API_KEY` 只配置在 AI 服务，不能放入后端公开响应或任何 `VITE_` 变量。

## 调用方必须保持的行为

- JSON 字段使用小驼峰，实体编号为 UUID，时间带时区；REST 成功为 `{code:"OK",message,data}`，列表 data 为完整授权数组，错误 data 为 null。CSV 成功为文件，WebSocket 使用独立通知协议。
- 用户令牌只通过 Authorization 头发送；登录失效清理旧身份，角色拒绝按业务码提示。退出撤销当前会话，改密撤销全部设备会话。
- 学生提交仅携带 `{sessionId,emotion}` 和 `Idempotency-Key`；同次未知结果重试保持原键与载荷，新的主动反馈使用新键。HTTP 200 仍须检查成功包装和回执，不以本地记录代替入库确认。
- 九种情绪均可手动提交，AI 只映射七种基本表情；`FOCUSED`、`CONFUSED` 只用于手动反馈。AI 不上传用户编号、原始帧、人脸图像或特征。
- AI 低分回执为 `{accepted:false,reason:"LOW_CONFIDENCE"}`，接受回执为 `{accepted:true,created,record}`；created:false 的有效回执表示重复请求已确认。无效回执、网络失败或可重试状态保留稳定键与结构化结果。
- 历史和 HTTP 看板默认来源 ALL，统计与 CSV 默认 MANUAL；学生历史固定本人 MANUAL。查询时间使用 `[from,to)`，筛选与服务端授权取交集，不把页面分页当作全量统计。
- CSV 携带用户身份与当前筛选，成功按文件处理、失败按 JSON 错误处理。AI 自评分保留提供方与 self_reported，不描述为准确率或已校准概率。
- 实时连接先换取短期一次性票据，URL 仅携带 ticket 和可选 sessionId；收到版本变化后重新查询授权数据，重连重新换票，退出清理连接与定时器。
- AI 控制仅调用 `/api/admin/ai/*`，采集需明确启动。超时、无效回执或审计确认失败可能意味着操作已执行，先查询状态再决定是否重试；付费推理和控制请求不自动重放。

常见 HTTP / 业务码与调用处理见 [验收清单的错误处理表](backend-acceptance.md#错误处理核对)。

## 验证证据与结论边界

已验证代码基线为 [d17d114](https://github.com/pyrrolys1ne/Emoji-Based-Classroom-Mood-Checker-System/commit/d17d1145643ba3238476cb0dbf084f1d7359fdc2)。[后端及系统 CI](https://github.com/pyrrolys1ne/Emoji-Based-Classroom-Mood-Checker-System/actions/runs/42174360102) 与 [客户端 CI](https://github.com/pyrrolys1ne/Emoji-Based-Classroom-Mood-Checker-System/actions/runs/42174360115) 均通过：

| 检查            | 已验证结果                                                                         |
| --------------- | ---------------------------------------------------------------------------------- |
| 正式后端 pytest | 246 项通过，包含真实 PostgreSQL、HTTP、跨进程及重启验证                            |
| 相关模块回归    | AI 67 项、独立联调 7 项、管理端 36 项、客户端 65 项通过                            |
| 客户端浏览器    | 20 项通过，包含 Chromium、Firefox、手机视口及受控 HTTP                             |
| 类型与构建      | 共享契约和两个前端的类型检查、生产构建通过                                         |
| 正式链路        | 两个 API 模式生产构建、正式后端、真实 PostgreSQL 与独立 AI 服务的隔离模拟链路通过  |
| 容器链路        | CI 中的 Nginx HTTP / WebSocket 代理、AI 持久队列、服务重启及数据库备份恢复核对通过 |

上述自动化证明后端业务、权限和结构化接口链路，不证明 DeepFace 效果、真实摄像头、DeepSeek 实际调用、目标主机 HTTPS / WSS 或真实移动设备兼容性。对应项目在 [系统验收](system-acceptance.md) 中保持独立状态。当前查询返回完整数组，尚无服务端分页；现有测试不提供生产规模的容量或负载结论。
