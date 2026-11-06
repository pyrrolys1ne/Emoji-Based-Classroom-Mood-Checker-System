# 实时看板与 AI 控制代理

正式后端提供持久化一次性票据、按身份过滤的 WebSocket 刷新通知、实时记录快照和管理员 AI 控制代理。健康接口 stage 为 realtime-ai-control。统计与导出见 [统计说明](backend-statistics.md)，匿名写入见 [AI 入库](backend-ai-ingestion.md)。

## 迁移与配置

启动前执行数据库迁移至 `007_realtime_revision.sql`。新增 class_session.revision 及事务触发器；记录、名单、课堂、课程名称及相关学生资料变更会更新对应课堂版本，事务回滚不会留下通知。用户改密不改变课堂内容版本，但撤销登录会话。已有记录、身份、票据和 AI 回执保留，不改写历史迁移。

| 配置                       | 用途                                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------- |
| MOOD_CORS_ORIGINS          | 允许的浏览器来源列表，必须精确包含页面的协议、主机与端口；也用于 WebSocket Origin 校验 |
| MOOD_WS_TICKET_TTL_SECONDS | 默认 30，范围 1—30；实际票据不晚于登录会话到期                                         |
| MOOD_REALTIME_POLL_SECONDS | 默认 1，范围 0.1—5；每个连接检查数据库中的身份、范围和版本的间隔                       |
| MOOD_AI_BASE_URL           | AI 服务固定根地址，默认 http://127.0.0.1:8001；不接受浏览器指定目标地址                |
| MOOD_AI_CONTROL_TOKEN      | 后端专用控制令牌，匹配 AI 服务 AI_CONTROL_TOKEN                                        |
| MOOD_AI_SERVICE_TOKEN      | 与控制令牌隔离的入库令牌，匹配 AI 服务 AI_SERVICE_TOKEN                                |
| MOOD_ALLOW_SIMULATED_AI    | 默认 false；只有与正式数据隔离的开发数据库才能显式开启模拟启停与入库                   |

按 [数据库说明](backend-database.md) 配置连接和迁移，按 [AI 服务说明](admin-ai.md) 启动独立进程。服务启动、读取状态和打开页面均不会启动摄像头或付费推理。真实采集须由管理员明确点击启动；远程摄像头另需允许发送、次数及时间上限。

后端可多进程共享同一 PostgreSQL；AI 控制地址对应一个采集进程，其任务状态、设备和重试队列由该进程管理。

## 票据与 WebSocket

教师、管理员使用用户 Bearer 令牌调用 `POST /api/auth/ws-ticket`。成功 data 为 `{ticket,expiresAt}`，禁止缓存；学生与 AI 服务身份不能换票。票据为 wst_ 前缀的随机不透明值，数据库只存 SHA-256 摘要，并绑定当前登录会话。

浏览器连接 `/ws/dashboard?ticket=<短期一次性票据>`，可附加 sessionId 限定课堂；URL 不携带用户访问令牌。来源必须精确匹配 MOOD_CORS_ORIGINS，缺少、null 或其他来源均拒绝。非法或重复参数、非票据认证、过期或已消费票据被拒绝；票据在数据库事务中原子消费，不同后端进程并发使用只成功一次。来源拒绝不会消费票据，其他未通过连接可消耗已校验票据。

连接发送的结构为 `{type:"snapshot",total,latestId,version}`：

- total 为当前授权课堂中可见记录条数，latestId 为按 recordedAt、id 倒序的第一条记录编号或 null。学生身份字段、原始影像、分数和完整记录不通过此通道广播。
- version 为授权课堂编号与版本的不可读摘要，可用于识别名单、课程名或资料变化，即使记录数量不变也会刷新。教师只受自己所授课堂变化影响，课程默认教师变更不转移已有课堂权限。
- 计数、最新编号和课堂版本来自同一 SQL 快照。正式默认隐藏模拟记录，模拟记录写入不改变正式版本；隔离环境开启后仍由可见记录计数通知新增模拟结果。

连接期间每次推送前重新读取登录会话、账号状态、角色和课堂范围。注销撤销当前设备会话及未消费票据，改密撤销全部设备；相应连接在下一次检查时关闭。禁用、到期、教师身份变化或指定课堂越权也关闭连接。1008 表示身份、来源、范围或协议被拒绝，1011 表示服务端暂时无法完成检查；连接不接收客户端业务消息。

版本存于 PostgreSQL，支持跨进程写入、读取及重启，不依赖单个进程的票据字典或消息队列。管理端在通知变化后重新读取授权 HTTP 接口；断线指数退避重连，每次重连重新换票，保留 5 秒可见页面轮询。页面退出清理连接和定时器；身份失效清除旧个人状态。课堂外的用户目录变化也由常规轮询更新。

## HTTP 实时快照

`GET /api/admin/dashboard/realtime` 允许教师和管理员，支持与历史相同的 sessionId、userId、course、class、from、to、source、emotion 筛选，source 默认 ALL。成功 data 为 `{records,total,latestId,updatedAt}`，records 为完整授权 EmojiRecord 数组，total 和 latestId 取自该数组。列表保持时间与编号倒序，不静默截断。

学生不能查询此接口。显式未知课堂返回 404，教师显式查询其他任课人的课堂返回 403；时间与筛选校验同 [历史说明](backend-feedback.md)。WebSocket 只通知刷新，HTTP 接口负责实际数据访问和服务端权限过滤。

## 管理员 AI 代理

| 正式后端接口                     | AI 内部接口                 | 行为                                                     |
| -------------------------------- | --------------------------- | -------------------------------------------------------- |
| GET /api/admin/ai/status         | GET /control/status         | 查询任务、计数、队列与停止原因                           |
| POST /api/admin/ai/start         | POST /control/start         | 校验课堂与采样配置后明确启动                             |
| POST /api/admin/ai/stop          | POST /control/stop          | 请求停止；正在结束推理时 running 可暂时为 true           |
| GET /api/admin/ai/vision         | GET /control/vision         | 查询公开样本清单和是否配置，不返回密钥或图像             |
| POST /api/admin/ai/analyze-image | POST /control/analyze-image | 仅分析清单中已准备的公开样本，需单次远程发送授权，不入库 |

所有接口仅管理员可用，用户身份不转发到 AI 服务；后端独立添加控制令牌。目标固定，不跟随重定向、不自动重试控制或付费请求。未配置控制令牌或无法连接返回 503；超时返回 504；上游认证错误或无效回执返回 502，不误判为用户登录失效，也不回显上游错误正文。

start 只接受共享 AIConfig：sessionId、mode、sampleIntervalSeconds、confidenceThreshold、cameraIndex、allowRemoteUpload、maxSamples、maxDurationSeconds。课堂必须存在且处于 `[startsAt,endsAt)`；模拟模式还需环境显式允许。间隔范围 0.5—60 秒、阈值 0—1、设备编号 0—10；camera-api 需要 allowRemoteUpload=true、间隔至少 5 秒、采样数 1—60、时长 10—600 秒。默认值和字段见 OpenAPI；不接收图像、视频或任意服务 URL。

analyze-image 只接受 `{imageId,allowRemoteUpload:true}`。编号不得包含路径或 URL，必须属于 AI 服务返回的样本清单并已准备，且识图配置有效。结果保留 sampleOnly=true、persisted=false、confidenceKind=self_reported、calibrated=false，基本表情映射须一致；不允许 FOCUSED 或 CONFUSED，也不把自评分描述为准确率。公开样本与摄像头授权相互独立。

后端验证状态、配置、计数、时间和表情结构，只返回已定义字段；上游原始错误替换为固定提示，不能把服务端令牌、密钥字段、文件路径或原始图像透传到浏览器。状态响应不表示摄像头或模型已通过效果验收。

## 审计与未知结果

启停和图片分析先提交 AI_START_REQUEST、AI_STOP_REQUEST 或 AI_IMAGE_ANALYZE_REQUEST，之后使用同一操作编号记录 SUCCESS、REJECTED 或 UNKNOWN。控制命令按数据库事务锁串行，执行前重新验证管理员身份；意图提交失败不会发出外部操作。

外部设备、付费请求与本地数据库无法共同回滚。回执丢失、无效或成功审计失败时，任务可能已经执行；响应明确提示先核实再决定是否重试，不能将其当作安全失败后自动重放。一般网络超时为 8 秒，单图代理为 40 秒，页面为 45 秒；这些是连接与读写超时设置，排队或前置样本核对也会占用时间。页面不会自动重试写请求，停止响应仍运行时会显示等待结束。

## 验证

安装后端开发依赖和 AI 服务基础依赖，设置 MOOD_TEST_DATABASE_URL 后，在 services/backend 执行 `../../.venv/bin/python -m pytest -q`。测试创建独立临时库，覆盖票据摘要、过期与并发、来源、角色、课堂、撤销、版本与回滚、代理参数、敏感响应过滤、未知结果及审计失败。

真实进程测试启动两个后端和独立 AI 服务，验证跨进程通知、重启票据、隔离模拟采样到入库、管理员启停和注销关闭连接；不运行摄像头或远程付费推理。前端运行类型检查、测试与构建，验证换票、版本刷新、断线退避、轮询和退出清理。真实模型、摄像头和部署环境仍需单独验收。
