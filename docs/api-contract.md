# API 协作草案

## v0.4 摄像头 API 实验增量

AI 启动模式新增 `camera-api`。该模式要求 `allowRemoteUpload: true`、`sampleIntervalSeconds >= 5`，并使用 `maxSamples`（默认 5，范围 1—60）和 `maxDurationSeconds`（默认 120，范围 10—600）限制实验。到达任一上限停止新采样；正在进行的设备读取或请求结束后退出。错误响应或无效 API 结果停止实验，不自动重试付费推理；结构化入库仍使用原有重试和幂等机制。

AI 状态新增 `apiCalls`、`lastInferenceMs`、`lastInferenceAt`、`lastFaces: [{emotion, score}]` 与 `stopReason`（`REQUESTED`、`MAX_SAMPLES`、`TIME_LIMIT`、`ERROR`）。手动停止期间返回仍在运行时，表示正等待设备或上游调用结束；不会继续采样，当前调用返回结果不入库。状态不包含图像。

AI 入库新增可选 `inferenceProvider`（`DeepSeek` 或 `DeepFace`）、`confidenceKind`（`self_reported` 或 `model_score`）。DeepSeek 必须配套 `self_reported`，否则返回 422。远程摄像头记录为 `source: AI`、`simulated: false`、匿名用户，`recordedAt` 取采样时刻，`deviceId` 为 `camera-api-{index}`。幂等载荷比较、历史查询与 CSV 保留新增字段；PostgreSQL 结构变更见 `003_inference_metadata.sql`。正式后端仍为占位，迁移与业务持久化须在正式环境验证。

## v0.3 图片分析增量

以下接口已由独立联调服务和 AI 服务实现；正式后端尚未实现。既有 v0.2 业务契约保持有效。

| 管理员代理                         | AI 内部控制接口               | 行为                                           |
| ---------------------------------- | ----------------------------- | ---------------------------------------------- |
| `GET /api/admin/ai/vision`         | `GET /control/vision`         | 返回提供方、模型、是否配置和样本可用性，无密钥 |
| `POST /api/admin/ai/analyze-image` | `POST /control/analyze-image` | 单张公开样本远程表情分析，不入库               |

请求必须包含 `imageId` 和 `allowRemoteUpload: true`，禁止其他字段。编号只能来自服务端样本清单，不接受任意路径或 URL。管理员代理要求用户管理员身份，内部接口要求独立 AI 控制令牌。未授权返回 401，教师返回 403，无效参数返回 422，缺少样本返回 404，未配置密钥返回 503，上游错误或无效结果返回 502。提供方密钥不经浏览器传输。

响应结构见共享类型 `VisionStatus`、`VisionResult`。分析包含 `faces: [{ label, score, emotion }]`，无脸返回空数组，不确定返回 `emotion: null`。`confidenceKind: "self_reported"` 与 `calibrated: false` 明确分数未经校准，`sampleOnly: true`、`persisted: false` 表示结果不写入课堂统计。调用超时分别为 AI 上游 30 秒、代理 40 秒、页面 45 秒，不自动重试付费推理。详情见 [图片 API 说明](image-api.md)。

## v0.2 基线

版本：v0.2 管理端与 AI 协作草案。正式后端 `services/backend` 仍为占位，原表记录其当前行为。独立本地参考服务 `services/integration` 已实现下文新增约定，不能替代正式后端；业务接口应符合相关契约。

统一响应结构：

```json
{ "code": "OK", "message": "成功", "data": {} }
```

错误结构相同，`data` 为 `null`。常用错误码为 `UNAUTHENTICATED`、`FORBIDDEN`、`NOT_FOUND`、`VALIDATION_ERROR`、`NOT_IMPLEMENTED`、`UNAVAILABLE` 和 `INTERNAL_ERROR`。校验错误不回显密码等输入值。

| 模块     | 已预留接口                                                               | 当前行为                   |
| -------- | ------------------------------------------------------------------------ | -------------------------- |
| 健康     | `GET /api/health`                                                        | 200，进程运行状态          |
| 就绪     | `GET /api/ready`                                                         | 200 或 503，检查数据库连接 |
| 账号     | `POST /api/auth/register`、`POST /api/auth/login`                        | 校验请求后返回 501         |
| 改密     | `PUT /api/auth/password`                                                 | 受保护占位接口             |
| 用户     | `GET /api/users/me`、`GET /api/admin/users`                              | 受保护占位接口             |
| 课堂     | `GET /api/sessions`、`POST /api/admin/sessions/{session_id}/schedule`    | 受保护占位接口             |
| 情绪     | `POST /api/emoji`、`GET /api/emoji/history`、`GET /api/emoji/statistics` | 受保护占位接口             |
| 看板     | `GET /api/admin/dashboard/realtime?sessionId=...`                        | 受保护占位接口             |
| 多维统计 | `GET /api/admin/statistics?course=&class=&from=&to=`                     | 受保护占位接口             |
| 导出     | `GET /api/admin/emoji/export?format=csv`                                 | 受保护占位接口             |
| AI       | `POST /api/ai/emoji-results`                                             | 独立令牌验证后返回 501     |
| 实时推送 | `WebSocket /ws/dashboard`                                                | 拒绝连接，鉴权及推送待实现 |

受保护占位接口无令牌时返回 401，有占位令牌时返回 501，不会将任意令牌视为有效用户。AI 接口未配置令牌时返回 503，令牌不匹配返回 401。

JSON 字段使用小驼峰，例如手动提交为 `sessionId`、`emotion`；安排用户为 `userIds`；AI 入库为 `sessionId`、`emotion`、`confidence`、`recordedAt`、`deviceId`、`source`。时间戳须使用带时区的 ISO 8601 格式，来源限定 AI，置信度在零到一之间。当前情绪枚举为 `HAPPY`、`FOCUSED`、`NEUTRAL`、`CONFUSED`、`SAD`，应与共享类型保持一致。

公开注册不能提交 `ADMIN` 角色。教师注册后的角色审批、管理员创建机制和权限矩阵仍需确定。教师必须能访问所授课堂的看板和统计，即使路径包含 `admin` 也应按照实际权限授权。

前端 API 适配层暂定列表响应的 `data` 为数组；未来增加分页时需统一改为 `items`、`total` 等结构并同步类型与页面。服务端 CSV 导出和浏览器演示导出是不同实现，正式 CSV 接口仍待开发。

## 管理端与 AI 接口

- 登录成功返回 `data: { token, user }`，用户包含 `id`、`username`、`email`、`role`、`status`。管理端接受管理员或教师。
- `POST /api/auth/logout` 撤销令牌，关闭使用该会话的实时连接。
- `POST /api/auth/ws-ticket` 携带用户令牌换取 `data: { ticket }`，票据一次性使用，30 秒有效。
- `WebSocket /ws/dashboard?ticket=...` 校验来源、票据与可见课堂范围，发送 `{ type: 'snapshot', total, latestId }`；前端事件刷新，断线重连，5 秒轮询兜底。URL 不携带可复用访问令牌。
- `GET /api/admin/ai/status`、`POST /api/admin/ai/start`、`POST /api/admin/ai/stop` 为管理员专用的 AI 控制代理。服务令牌不能出现在浏览器请求与响应。
- 启动请求为 `sessionId`、`mode`（`simulation` 或 `camera`）、`sampleIntervalSeconds`（0.5—60）、`confidenceThreshold`（0—1）、`cameraIndex`（0—10）。状态结构见共享契约 `AIStatus`。
- AI 内部 `/control/status`、`/control/start`、`/control/stop` 使用独立 `AI_CONTROL_TOKEN`。
- AI 入库增加可选 `simulated`，必须携带稳定 `Idempotency-Key`。成功为 `data: { accepted: true, created, record }`；低置信度丢弃为 `data: { accepted: false, reason: 'LOW_CONFIDENCE' }`。同键去重，同键不同内容返回 409。正式环境默认拒绝模拟输入。
- 情绪枚举增加 `ANGRY`、`SURPRISED`、`FEAR`、`DISGUST`，附有数据库迁移脚本；`FOCUSED`、`CONFUSED` 不从模型推断。模型只映射七种基本表情。
- 统计 `from`、`to` 为带时区的 ISO 时间，采用 `[from, to)`，非法参数返回 422。参考统计返回 `data: { total, distribution }`。正式分页前需补充服务端趋势和分组模型，不能仅统计某一页数据。

管理员用户目录与安排仅限管理员；教师只访问所授课堂的历史、看板和统计。参考服务不实现正式注册、密码哈希或用户管理写操作，合成账号严禁用于生产。原表及上文五类情绪描述保留了 v0.1 基线，新增内容以本节为准。
