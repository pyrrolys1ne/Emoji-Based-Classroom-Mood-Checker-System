# API 协作草案

版本：v0.1 框架草案。可执行契约以启动后的 `/openapi.json` 为准。业务接口尚未实现，响应数据模型需在各模块联调前补齐并共同确认。

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
