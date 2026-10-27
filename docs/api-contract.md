# API 协作草案

版本：v0.2 管理端与 AI 协作草案。正式后端 `services/backend` 仍为占位，原表记录其当前行为。独立本地参考服务 `services/integration` 已实现下文新增约定，不能替代正式后端；正式后端负责人需确认并实现相关契约。

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

## 管理端与 AI 迭代新增契约

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
