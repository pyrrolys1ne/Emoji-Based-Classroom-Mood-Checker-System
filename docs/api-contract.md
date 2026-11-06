# API 协作草案

## v0.9 匿名 AI 入库

正式后端已实现 `POST /api/ai/emoji-results`，使用独立 AI 服务令牌并返回统一包装。请求、错误与运行配置见 [AI 入库说明](backend-ai-ingestion.md)。本节覆盖旧版本 AI 入库状态，统计、导出、实时及 AI 控制代理仍未实现。

- 请求使用既有 AIResult：`sessionId,emotion,confidence,recordedAt,deviceId` 必填，source 省略时为 AI，simulated 默认为 false，提供方和分数类型可空。confidence 必须为有限 JSON 数值且在 0—1 内，simulated 必须为布尔值；不接受用户编号、图像、视频、人脸特征或其他额外字段。只允许七种基本表情，DeepSeek 必须保留 self_reported 类型。
- 新请求先验证课堂存在，采样时间必须带时区、不能晚于服务端当前时间，且属于 `[startsAt,endsAt)`。允许课后补传有效采样，不要求接收时间仍在课堂内；未知课堂返回 404，未来采样返回 422 INVALID_RECORD_TIME，课堂时段外返回 409 CLASSROOM_NOT_OPEN。
- 默认拒绝 simulated，返回 403 SIMULATED_AI_DISABLED；隔离开发数据库显式开启 MOOD_ALLOW_SIMULATED_AI 后才可写入。关闭配置后同时禁止模拟重放并在历史中隐藏模拟记录。正式与模拟环境不混用数据。
- 低于 MOOD_AI_MIN_CONFIDENCE（默认 0.5）返回 `{accepted:false,reason:"LOW_CONFIDENCE"}`，不创建情绪或接受审计；等于阈值可入库。接受返回 `{accepted:true,created:true,record}`，同键同载荷重放 created 为 false。record 的 userId、student 均为 null，来源为 AI，保留采样时间、设备标识（数据库字段）、模拟标记、提供方和分数类型；公开记录沿用 EmojiRecord，不公开设备编号。
- Idempotency-Key 必填，AI 命名空间与学生手动命名空间隔离。所有已完成接受和过滤均保存请求摘要与回执，同键不同载荷返回 409 IDEMPOTENCY_CONFLICT；省略的默认值、等值数值、等值时区、标准 UUID 和去除首尾空白的设备标识参与规范化。阈值变化不改变已有结果，非法请求不占用键。
- 新增迁移 006_ai_ingestion.sql，将已有带键 AI 记录回填为接受回执，保留既有记录和手动键。按键事务锁协调多个进程，数据库唯一约束防重复；接受记录、回执和 AI_RESULT_ACCEPT 审计在同一事务提交，服务身份的 audit.actorId 为 null。过滤回执也须提交成功后才返回；失败回滚，原键可重试。
- AI 服务只在收到完整、有效且与原载荷一致的接受回执，或明确 LOW_CONFIDENCE 过滤回执时移除待上报项。网络失败、408、429、5xx 或无效回执保持稳定键和原载荷并退避重试；其他非成功状态停止当前采集并保留待上报队列，修正配置或数据问题后显式重启。原始帧不进入队列或入库接口。

## v0.8 手动反馈与授权历史

正式后端已实现 `POST /api/emoji` 和 `GET /api/emoji/history`；成功响应在事务提交后返回，接口示例见 [手动反馈与历史](backend-feedback.md)。本节覆盖较旧版本的反馈与历史实现状态，统计、导出、实时和 AI 入库仍未开放。

- 手动提交仅限启用且具备有效会话的学生。请求体仅 `{sessionId,emotion}`，九种情绪均允许；身份、MANUAL 来源、UTC 记录时间由服务端确定。新记录必须属于当前名单且满足 `[startsAt,endsAt)`；等待用户或课堂锁后重新采样服务端时间。不存在课堂返回 404，无安排返回 403，时段外返回 409 CLASSROOM_NOT_OPEN。
- `Idempotency-Key` 必填，按学生和 MANUAL 来源唯一。同键同规范化载荷返回同一记录，同键不同课堂或情绪返回 409 IDEMPOTENCY_CONFLICT；新键产生新记录。成功重放不增加记录或审计，允许在课堂结束或移出名单后读取原记录，仍须有效学生身份。反馈和 EMOJI_MANUAL_SUBMIT 审计原子提交，失败回滚；键与 SHA-256 请求摘要不进入公开响应。
- 历史支持 `sessionId,userId,course,class,from,to,source`；默认 ALL，按记录时间倒序、编号倒序返回完整数组，不静默截断。时间必须带时区，采用 `[from,to)`。未知参数、非法 UUID、非法来源或无效时间范围返回 422。响应时间统一 UTC。
- 学生历史固定为本人 MANUAL；显式查询其他 userId 或 AI 返回 403。教师限定课堂实际 teacherId，管理员全量；筛选与身份范围取交集。显式 sessionId 不存在返回 404，越权返回 403；学生当前被安排或已有本人手动记录即可查询该课堂的本人历史。移出名单不删除历史，也不重新允许新增。
- EmojiRecord 增加 `classroom` 与 `student` 摘要。classroom 为 `{id,courseId,courseName,teacherId,teacherName,className,room,startsAt,endsAt}`，不含名单；student 为 `{id,username,studentNo,realName,className,status}`，AI 为 null。正式响应总是返回摘要，按当前授权范围读取当前资料；重放保证记录编号、时间、内容一致，不冻结后续资料更正。共享 TypeScript 字段可选以兼容演示和联调数据。
- AI 历史保持匿名和原有提供方、自评分类型，不归属个人；默认隐藏 simulated 记录，仅隔离环境允许显式配置纳入并保持标记。读取已有 AI 数据不表示 AI 入库已实现。客户端校验手动成功回执与提交一致，成功后刷新历史；无效回执视为结果未知并保留重试键，不能显示保存成功。
- 反馈、历史成功及错误响应均设 `Cache-Control: no-store`。退出、改密及账号状态变化继续作用于反馈和历史，持久化记录及幂等键在服务重启后保留。

## v0.7 课程课堂与学生安排

正式后端已实现课程查询与创建修改、课堂创建修改、学生资料维护、名单替换和按角色过滤的课堂查询，接口与初始化文件见 [课程课堂说明](backend-classrooms.md)。成功列表为数组，写操作在数据库及审计提交后返回成功。

- 新增 `GET/POST /api/admin/courses`、`PUT /api/admin/courses/{course_id}`、`POST /api/admin/sessions`、`PUT /api/admin/sessions/{session_id}`、`PUT /api/admin/users/{user_id}/student-profile`；仅管理员可用。学生资料写入返回 User，课程写入返回 Course，课堂写入返回 ClassSession。
- 既有 `GET /api/sessions` 和 `POST /api/admin/sessions/{session_id}/schedule` 已实现；名单替换成功 data 为 null，最多 500 个 UUID，重复值去重，空数组清空。只能新安排启用且符合学生身份的账号，无效输入返回 422 INVALID_STUDENT 并保留原名单。
- ClassSession 新增实际任课 teacherId 和 scheduledStudents。课堂教师独立于课程默认教师；迁移 005 按原课程教师回填，之后修改课程默认教师不改变已有课堂权限。SessionRequest 新增可选 teacherId：新建省略时用课程默认教师，修改省略时保留原任课人，显式 null 返回 422。教师必须启用且已获 APPROVED，否则返回 422 INVALID_TEACHER。
- 管理员获取全部课堂；教师按课堂实际 teacherId 过滤；学生仅获取被安排课堂，且 scheduledUserIds 与 scheduledStudents 仅包含本人。教师和管理员的名单摘要为 `{id,username,studentNo,realName,className,status}`，不包含邮箱、哈希或令牌。课堂按 startsAt、id 升序，范围和名单同一 SQL 查询读取。
- 课堂开始或已有记录后禁止修改课程、教师与起止时间，返回 409 CLASSROOM_LOCKED；在其他参数合法时可更正教室、班级。未来且无记录的课堂可调整。名单更新与班级资料维护不删除或转移历史记录，也不按学生所属班级自动安排。
- 学生资料至少提交一个允许字段，省略保留，null 清空，学号唯一；冲突返回 409 STUDENT_NO_EXISTS。管理接口不接受 role、status、email 等额外字段，不赋予管理员或教师权限。
- `app.cli.import_classrooms` 通过密码验证管理员，使用稳定 importId 原子创建课程、课堂、名单和审计。重复批次返回 IMPORT_ALREADY_EXISTS，失败不保留批次编号；不自动创建账号、不发放用户令牌、不生成情绪记录。

TypeScript 的新增课堂字段保持可选，以兼容演示和独立联调服务；正式响应包含 teacherId 和 scheduledStudents，Python 请求模型、数据库迁移和客户端校验同步。手动反馈、历史、统计、导出、AI 入库及实时功能仍待实现。

## v0.6 账号与权限

正式后端已实现注册、登录、改密、注销、本人信息、管理员用户目录、教师申请查询与审核；实现和运行方法见 [账号认证与教师审批](backend-auth.md)。JSON 与共享 User、AuthSession、TeacherApplication 类型保持一致，成功响应及错误均为统一包装。与本节重复的业务状态以最新版本为准。

- 注册、改密和注销成功 data 为 null；登录成功为 `{token,user}`；本人信息为 User；目录为 User 数组；申请查询为 TeacherApplication 数组，审核返回更新后的 TeacherApplication。
- 公开 TEACHER 注册创建 STUDENT 用户与 PENDING 申请，不发放会话；待审核或驳回不能登录。管理员只能批准或驳回 PENDING，批准原子授予 TEACHER；不能通过请求授予 ADMIN。重复审核返回 409 CONFLICT。
- 密码使用 Argon2id 加盐哈希，用户令牌采用 `usr_` 加 256 位随机值的编码，数据库保存 SHA-256 摘要。多设备会话独立，退出撤销当前会话，改密撤销全部会话及票据；新旧密码相同返回 422。固定会话时长默认 8 小时，可配置，重启后会话可继续验证。
- 缺失、伪造、过期、撤销的用户令牌返回 401 UNAUTHENTICATED。登录账号密码错误亦返回同一 401 响应；密码正确但账号禁用返回 403 ACCOUNT_DISABLED，教师未获准返回 403 TEACHER_APPROVAL_REQUIRED；原密码错误返回 403 INVALID_PASSWORD。
- 管理员初始化仅提供受控命令，没有公开 HTTP 路径；已有管理员时拒绝重复初始化，也不提升已有账号。API 与命令均不返回密码哈希、会话摘要、数据库凭据或原始错误输入。
- 账号成功响应设置 Cache-Control: no-store；数据库连接故障返回 503 UNAVAILABLE。关键写操作与审计同事务，失败不会返回成功。
- 用户名去除首尾空白且区分大小写；邮箱做格式校验和域名规范化后按保存值唯一。输入长度与学生字段沿用 v0.5。AI 入库令牌和控制令牌不得使用保留前缀 usr_。

`GET /api/admin/teacher-applications`、`PUT /api/admin/teacher-applications/{application_id}` 已注册，仅管理员可用。学生不能访问用户目录、审批、统计、看板和导出；教师不能安排学生或导出；手动反馈仅限学生。反馈、历史、统计、导出及 AI 入库业务仍返回 501，WebSocket 仍拒绝连接。

## v0.5 后端基础契约

本节定义后端基础契约，与较新版本重复的实现状态以最新版本为准。正式后端已有请求校验、响应模型、数据库模型与迁移；反馈、历史、统计和导出业务仍未实现。数据库与配置见 [后端数据库说明](backend-database.md)。

### 账号与角色

`User` 保留 `id`、`username`、`email`、`role`、`status`，新增可选且可空的 `studentNo`、`realName`、`className`、`teacherApprovalStatus`。学号最长 50 字符且非空时唯一，姓名、班级最长 100 字符；旧账号允许为空。学生注册可提交前三项，教师申请只允许附加姓名。现有客户端注册表单仍兼容，资料维护和新增字段展示不表示已实现。

学生自助注册；`role: TEACHER` 表示申请教师身份，不能直接获得教师权限。申请记录状态为 `PENDING`、`APPROVED`、`REJECTED`，与用户的 `ACTIVE`、`DISABLED` 分离。申请者初始角色为 STUDENT，待审核和驳回时不发放登录会话；批准时由管理员在同一事务内授予 TEACHER 并记录审计。旧库已有教师保留授权。首个管理员由受控命令创建，公开注册不能选择 ADMIN。

登录返回 `{token,user}`，token 为高熵随机的不透明 Bearer 令牌。允许多设备登录，会话默认 8 小时，可配置；注销撤销当前会话，改密撤销全部会话及关联票据。数据库保存令牌 SHA-256 摘要。实时连接撤销在 WebSocket 功能实现时接入，当前不接受 WebSocket 连接。

### 课堂与手动提交

学生仅获取被安排课堂；教师仅获取所授课堂。学生提交时段为服务端时间的 `[startsAt,endsAt)`；允许多次新增记录，不覆盖既有反馈。请求体仍为 `{sessionId,emotion}`，身份、来源 MANUAL 和时间由服务端确定。

手动提交和 AI 入库均要求 `Idempotency-Key`，允许 1—100 个 ASCII 字母、数字及 `._:-`。一次用户操作生成一键；结果未知后重试沿用原键和原载荷，不自动重放写请求。手动键按用户隔离，AI 键按 AI 来源隔离。同键同载荷返回原结果，同键不同载荷返回 409；同一学生主动再次反馈使用新键。手动提交成功 data 为 EmojiRecord，重放返回同一条记录；注册成功 data 为 null。摘要由服务端对已校验、补齐默认值并规范化的请求计算，不接受客户端指定摘要。手动规范化载荷为 sessionId、emotion；AI 为所有已校验请求字段，时间转 UTC、UUID 使用标准形式，JSON 按字段排序后生成 SHA-256。鉴权与当前访问范围仍须校验；新记录需满足提交时段，已完成请求重放可在课堂结束后返回原结果。

缺少或非法幂等键返回 422。客户端 API 仓储已支持该请求头；同页、同账号、同课堂且选择不变的失败重试保留原键，刷新或切换后须先查历史核实。

### 查询与统计

历史、基础统计、多维统计及导出使用 `sessionId`、`userId`、`course`、`class`、`from`、`to`、`source` 过滤；服务端按当前身份进一步限制范围。时间必须带时区，使用 `[from,to)`；`from >= to` 或无时区返回 422。列表 `data` 保持数组，按 recordedAt 倒序、id 倒序稳定排序，不静默截断；分页变更须同步调用方。学生历史固定为本人 MANUAL 记录，不能通过 source 或 userId 扩大范围。

`source` 为 `MANUAL`、`AI`、`ALL`。历史默认 ALL；统计和 CSV 默认 MANUAL，显式 ALL 才合并。统计成功结构冻结为 `{total,distribution,source}`：distribution 包含九种情绪，未出现项为 0，总和等于 total；分母是相同范围和来源的记录数。必须全量聚合，AI 采样记录数不能解释为学生人数。共享类型保留 source 可选以兼容独立联调服务；正式成功响应应包含 source。统计来源切换界面和正式聚合在对应业务实现时接入。

### 新增管理接口约定

以下管理接口均已实现，当前响应与课堂教师扩展以 v0.7 为准。

| 接口                                                              | 请求与范围                                                                           |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `PUT /api/admin/users/{userId}/student-profile`                   | 管理员维护学生资料；可选 studentNo、realName、className，显式 null 清空，省略保留    |
| `GET /api/admin/teacher-applications`                             | 管理员查询申请；返回 id、userId、status、submittedAt、reviewedAt、reviewedBy、reason |
| `PUT /api/admin/teacher-applications/{applicationId}`             | `{decision:"APPROVED"或"REJECTED",reason?}`；只审核 PENDING，同事务更新角色与审计    |
| `GET /api/admin/courses`                                          | 管理员查询课程，返回 id、name、teacherId                                             |
| `POST /api/admin/courses`、`PUT /api/admin/courses/{courseId}`    | `{name,teacherId}`；必须是有效且已授予教师身份的用户                                 |
| `POST /api/admin/sessions`、`PUT /api/admin/sessions/{sessionId}` | `{courseId,startsAt,endsAt,room,className}`；带时区，结束晚于开始                    |

用户角色、有效教师、安排名单及数据范围由业务层在服务端校验。删除课程、删除课堂和新增管理页面不包含在上述接口中。

### 错误语义

统一错误包装不变。401 使用 UNAUTHENTICATED；403 可用 FORBIDDEN、ACCOUNT_DISABLED、TEACHER_APPROVAL_REQUIRED；404 使用 NOT_FOUND；409 可用 CONFLICT、ACCOUNT_EXISTS、STUDENT_NO_EXISTS、CLASSROOM_NOT_OPEN、IDEMPOTENCY_CONFLICT；422 使用 VALIDATION_ERROR；501 使用 NOT_IMPLEMENTED；503 使用 UNAVAILABLE。业务错误码在对应功能实现时启用，当前不伪造业务结果。

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

公开注册不能提交 `ADMIN` 角色。教师审批与管理员创建规则见 v0.5。教师必须能访问所授课堂的看板和统计，即使路径包含 `admin` 也应按照实际权限授权。

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
