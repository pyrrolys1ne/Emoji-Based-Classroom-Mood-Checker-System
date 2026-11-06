# API 契约

当前契约为 v0.12。正式后端已实现账号、课堂、手动反馈、匿名 AI 入库、历史、统计、CSV、实时授权和管理员 AI 控制；本页统一描述当前状态，具体请求模型与响应以共享类型、后端 Pydantic 和 `/openapi.json` 为准。模型、设备与部署验证见 [系统验收](system-acceptance.md)。

## 通用规则

- REST 根路径为 `/api`，JSON 使用小驼峰，正式实体编号使用 UUID，时间为带时区 ISO 8601，响应统一 UTC。时间查询采用起点包含、终点不包含的 `[from,to)`。
- 成功返回 `{code:"OK",message,data}`，错误返回 `{code,message,data:null}`。CSV 成功返回文件，WebSocket 为独立协议；不以演示数据替代真实接口结果。
- 用户认证为 `Authorization: Bearer <用户令牌>`。用户令牌、AI 入库令牌和 AI 控制令牌相互隔离；浏览器不持有 AI 令牌或模型密钥。
- 用户令牌使用随机不透明值，服务端只存摘要并校验会话、角色和数据范围。教师只访问课堂实际任课范围，学生只访问本人手动记录。课堂名单移除不删除既有历史。
- 列表 `data` 为完整授权数组；当前没有服务端分页，不能擅自截断后当作全量统计。正式统计与导出使用数据库全量范围，管理端表格分页只影响展示。
- 手动和 AI 上报要求稳定 `Idempotency-Key`；同键同规范化内容返回原结果，同键不同内容返回 409。用户手动键按本人隔离，AI 使用独立全局命名空间。
- 业务响应禁止缓存。缺失、伪造、过期、撤销令牌为 401；角色或范围拒绝为 403，未知课堂为 404，冲突为 409，非法请求为 422，数据库不可用为 503。请求未确认时保持结果未知，不自动重放写操作。

## 路由与角色

| 功能            | 路径                                                                                  | 访问与结果                                                                           |
| --------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 注册 / 登录     | `POST /api/auth/register`、`POST /api/auth/login`                                     | 注册仅 STUDENT / TEACHER，不能 ADMIN；教师需申请获准，登录返回 AuthSession           |
| 本人信息        | `GET /api/users/me`                                                                   | 当前有效用户，返回 User                                                              |
| 改密 / 注销     | `PUT /api/auth/password`、`POST /api/auth/logout`                                     | 改密撤销全部设备；注销只撤销当前会话及对应实时访问                                   |
| 用户目录        | `GET /api/admin/users`                                                                | 仅管理员，返回 User[]                                                                |
| 教师审批        | `GET /api/admin/teacher-applications`、`PUT /api/admin/teacher-applications/{id}`     | 仅管理员；只审批 PENDING，不授予 ADMIN                                               |
| 课程管理        | `GET/POST /api/admin/courses`、`PUT /api/admin/courses/{id}`                          | 仅管理员，Course / Course[]                                                          |
| 课堂查询        | `GET /api/sessions`                                                                   | 按学生名单或教师实际任课范围返回 ClassSession[]；管理员全量                          |
| 课堂管理        | `POST /api/admin/sessions`、`PUT /api/admin/sessions/{id}`                            | 仅管理员；课堂开始或已有记录后锁定课程、教师和时段                                   |
| 学生资料 / 名单 | `PUT /api/admin/users/{id}/student-profile`、`POST /api/admin/sessions/{id}/schedule` | 仅管理员；名单写入 `{userIds}`，空数组清空，不改变角色                               |
| 手动反馈        | `POST /api/emoji`                                                                     | 学生，`{sessionId,emotion}`，服务端确定身份、MANUAL 来源和记录时间，返回 EmojiRecord |
| 历史            | `GET /api/emoji/history`                                                              | 授权 EmojiRecord[]，默认来源 ALL；学生只能本人 MANUAL                                |
| 基础统计        | `GET /api/emoji/statistics`                                                           | 教师 / 管理员，Statistics，来源默认 MANUAL                                           |
| 多维统计        | `GET /api/admin/statistics`                                                           | 教师 / 管理员，MultidimensionalStatistics，来源默认 MANUAL                           |
| CSV             | `GET /api/admin/emoji/export?format=csv`                                              | 仅管理员，完整授权筛选集合，UTF-8 BOM、引号 / 换行转义与公式防护                     |
| HTTP 看板       | `GET /api/admin/dashboard/realtime`                                                   | 教师 / 管理员，`{records,total,latestId,updatedAt}`，来源默认 ALL                    |
| 实时票据        | `POST /api/auth/ws-ticket`                                                            | 教师 / 管理员，`{ticket,expiresAt}`，短期一次性且绑定当前会话                        |
| 实时通知        | `WebSocket /ws/dashboard?ticket=...&sessionId=...`                                    | 校验精确 Origin、身份与课堂范围；sessionId 可省略                                    |
| AI 上报         | `POST /api/ai/emoji-results`                                                          | 独立 AI 入库令牌；接受或低分过滤回执，匿名，不允许用户编号和原始影像                 |
| AI 控制         | `GET /api/admin/ai/status`、`POST /api/admin/ai/start`、`POST /api/admin/ai/stop`     | 仅管理员，经后端固定代理，浏览器只携带用户令牌                                       |
| 公开样本        | `GET /api/admin/ai/vision`、`POST /api/admin/ai/analyze-image`                        | 仅管理员，分析只接受清单编号与明确远程发送许可，不写课堂                             |
| 运行状态        | `GET /api/health`、`GET /api/ready`                                                   | 存活 / 数据库连通性；不等于迁移、模型或设备验证通过                                  |

## 记录、筛选与 AI

九种情绪为 `HAPPY`、`FOCUSED`、`NEUTRAL`、`CONFUSED`、`SAD`、`ANGRY`、`SURPRISED`、`FEAR`、`DISGUST`。AI 只映射其中七种基本表情，禁止推断 `FOCUSED`、`CONFUSED`。

历史、看板、统计和 CSV 共用 `sessionId,userId,course,class,from,to,source,emotion` 筛选，与服务端授权取交集；非法或未知参数拒绝。来源可为 MANUAL / AI / ALL，模拟记录默认排除，仅独立测试库显式允许。统计分母为记录条数，不是去重学生人数；timeline 为实际 UTC 时间升序的连续时间桶，groups 为课程与班级分组，均取自同一数据库快照。

EmojiRecord 包含记录编号、课堂、可空用户、情绪、来源、记录时间、可空模型分数、模拟标记与提供方 / 分数类型，以及 classroom、student 摘要。正式响应包含摘要；共享 TypeScript 摘要保持可选以兼容独立演示与参考服务。AI 的 userId 和 student 为 null，设备标识不进入公开历史；CSV 按管理员授权保留设备标识和自评分类型。

AIResult 必填 `sessionId,emotion,confidence,recordedAt,deviceId`，可选 `source:AI,simulated,inferenceProvider,confidenceKind`；confidence 为有限 0—1 数值，DeepSeek 必须标记 `self_reported`。采样发生在课堂时段且不晚于服务端当前时间，可以课后补传。低分返回 `{accepted:false,reason:"LOW_CONFIDENCE"}`；接受返回 `{accepted:true,created,record}`。接受与过滤均持久化回执，重启和阈值改变不会重写原结果。自评分不能描述为准确率或已校准概率。

## 实时与控制

实时票据默认 30 秒且不晚于用户会话过期，数据库原子消费，跨进程不可重放。连接仅允许 ticket 和可选 sessionId，不接受用户访问令牌或其他参数。服务端发送 `{type:"snapshot",total,latestId,version}`，不广播完整记录；version 为授权课堂版本摘要。持续检查当前身份，注销、改密、禁用、到期或角色 / 范围变化时关闭。1008 表示身份、来源、范围或协议拒绝，1011 表示服务端检查失败。前端重连换票并保留轮询兜底。

AIConfig 包含 `sessionId,mode,sampleIntervalSeconds,confidenceThreshold,cameraIndex,allowRemoteUpload,maxSamples,maxDurationSeconds`。mode 为 simulation / camera / camera-api；间隔 0.5—60 秒、阈值 0—1、设备 0—10，camera-api 需要明确允许远程发送且间隔至少 5 秒、次数 1—60、时长 10—600 秒。启动必须关联正在进行的课堂；模拟仅在环境明确允许时可用，重启服务不自动启动采集。

后端代理剔除未知和敏感字段，不自动重试控制或付费推理；操作以同一编号审计 REQUEST 与 SUCCESS / REJECTED / UNKNOWN。未配置 / 不可连接为 503，上游认证或无效回执为 502，超时为 504，忙碌为 409，限流为 429。网络副作用与数据库不能共同回滚，超时或确认失败须提示结果可能未知。

## 详细说明

- [账号认证与审批](backend-auth.md)
- [课程课堂与学生安排](backend-classrooms.md)
- [手动反馈、幂等与历史](backend-feedback.md)
- [匿名 AI 入库与重试](backend-ai-ingestion.md)
- [统计、时间桶与 CSV](backend-statistics.md)
- [实时看板与 AI 控制](backend-realtime-ai.md)
- [数据库与迁移](backend-database.md)、[部署与恢复](deployment.md)

`services/integration` 仅使用合成账号和 SQLite 做开发联调，不替代正式后端认证、数据库或部署验收。
