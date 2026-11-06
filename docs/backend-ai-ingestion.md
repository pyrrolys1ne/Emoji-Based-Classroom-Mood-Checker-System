# 匿名 AI 入库

正式后端通过 `POST /api/ai/emoji-results` 接收独立 AI 服务的匿名结构化结果。接口只保存情绪记录，不接收原始视频帧、人脸图像、人脸特征或用户身份；不会启动摄像头或调用模型。历史权限沿用 [手动反馈与历史](backend-feedback.md)，统计和导出见 [统计导出说明](backend-statistics.md)，实时与管理员 AI 控制代理见 [实时说明](backend-realtime-ai.md)。

## 数据库与配置

启动前执行 [数据库迁移](backend-database.md)，升级至 `006_ai_ingestion.sql`。新增 ai_ingestion 保存幂等键、请求摘要、接受记录编号或 LOW_CONFIDENCE 过滤原因及创建时间。迁移将已有带键 AI 记录回填为接受回执，不删除情绪记录、不接管学生手动键。历史无键记录保持原样。

| 后端配置                | AI 服务配置                           | 用途                                                                |
| ----------------------- | ------------------------------------- | ------------------------------------------------------------------- |
| MOOD_AI_SERVICE_TOKEN   | AI_SERVICE_TOKEN                      | 同一独立入库令牌；空配置禁用，不使用用户令牌保留前缀 usr_           |
| MOOD_AI_CONTROL_TOKEN   | AI_CONTROL_TOKEN                      | 独立控制令牌，不能代替入库令牌；正式控制代理已接入                  |
| 后端监听地址            | AI_BACKEND_URL                        | AI 连接正式后端的根地址，例如 http://127.0.0.1:8000，不附加 /api    |
| MOOD_AI_MIN_CONFIDENCE  | /control/start 的 confidenceThreshold | 后端独立校验阈值，默认 0.5；采集端过滤不能替代后端检查              |
| MOOD_ALLOW_SIMULATED_AI | /control/start 的 mode                | 默认 false；模拟仅在隔离开发数据库显式开启，记录保留 simulated 标记 |

配置分别位于 `services/backend/.env`、`services/ai/.env`，实际值不提交版本库。AI_OUTBOX_PATH 指定结构化重试队列路径，队列跨服务重启保留稳定键与原载荷。原始帧只在采样与推理内存中存在。

## 请求与响应

```http
POST /api/ai/emoji-results
Authorization: Bearer <独立 AI 入库令牌>
Idempotency-Key: <本条采样结果的稳定键>
Content-Type: application/json

{"sessionId":"11111111-1111-4111-8111-111111111111","emotion":"HAPPY","confidence":0.8,"recordedAt":"2026-11-06T02:15:00Z","deviceId":"camera-api-0","source":"AI","simulated":false,"inferenceProvider":"DeepSeek","confidenceKind":"self_reported"}
```

示例编号和时间须替换为实际课堂与采样时间。sessionId 为 UUID；deviceId 去除首尾空白后长度为 1—100。confidence 为有限 JSON 数值，范围 0—1；simulated 必须是布尔值。允许 HAPPY、NEUTRAL、SAD、ANGRY、SURPRISED、FEAR、DISGUST；FOCUSED、CONFUSED 仅供手动反馈。source 可省略，提供方和分数类型可省略或为 null；DeepSeek 必须搭配 self_reported，该分数未经校准，不能称为准确率或校准概率。

采样时间必须带时区、不能晚于服务器当前时间，并落在课堂 `[startsAt,endsAt)` 内。课后补传仍按原始采样时间验证，不把接收时间当作采样时间。设备与服务器应保持时钟同步。课堂存在和时间合法之后才执行后端阈值过滤。

成功包装为 `{code:"OK",message:"成功",data:...}`。data 有两种：

- 接受：`{accepted:true,created:true,record:EmojiRecord}`。重放已成功请求时 created 为 false，记录编号、采样时间和内容保持一致；课堂展示摘要读取当前资料。
- 过滤：`{accepted:false,reason:"LOW_CONFIDENCE"}`。低于阈值不创建情绪记录；等于阈值可以接受。过滤不是保存成功，发送端将其计为 filtered。

接受记录的 userId、student 为 null，source 为 AI；记录保留原始采样时间、模拟标记、提供方与分数类型。设备编号保存于数据库；公开 EmojiRecord 与历史不返回 deviceId、内部幂等键或请求摘要。

## 幂等与事务

键允许 1—100 个 ASCII 字母、数字及 `._:-`，AI 队列为每条结果生成独立 UUID，重试保持原键和原载荷。AI 键全局唯一，与学生手动键分开。

服务端对已校验并补齐默认值的全部 AIResult 字段计算规范化摘要：UUID 使用标准形式，时间转 UTC，设备标识去除首尾空白，等值数值使用相同表示，字段排序后编码为紧凑 JSON 并计算 SHA-256。客户端不能指定摘要。

同键同载荷重放原有接受或过滤结果；同键不同载荷返回 409。即使阈值调整，已过滤结果也不自动转为记录。模拟策略在重放前检查，关闭模拟配置后不能重放模拟请求。其他非法请求不会占用键，修正后可沿用原键。

按键事务锁协调多个后端进程，随后锁定目标课堂并验证。接受时情绪记录、接受回执和 AI_RESULT_ACCEPT 审计共同提交；服务身份无用户编号，审计 actorId 为 null。过滤回执单独提交，且不创建接受审计。任何失败均回滚，不能返回虚假接受或过滤。数据库主键、唯一索引和外键提供额外约束。

AI 服务校验成功包装、accepted、created、记录编号，以及课堂、时间、情绪、来源、匿名身份、分数、模拟标记和提供方类型。回执缺失或与原载荷不一致时保留队列并退避；不会仅凭 HTTP 200 或 accepted:true 出队。明确过滤回执才增加 filtered；created:false 的有效回执也可完成投递。

网络失败、408、429 和 5xx 退避重试，最多等待 30 秒；非成功的其他状态停止当前任务并保留队列，修正原因后显式启动。响应丢失时原请求可能已经提交，稳定键确保服务重启后重试不会重复入库。

## 错误与权限

| HTTP 与业务码             | 含义                                           |
| ------------------------- | ---------------------------------------------- |
| 401 UNAUTHENTICATED       | 缺少或无效 AI 入库令牌；用户及控制令牌不能代用 |
| 403 SIMULATED_AI_DISABLED | 当前环境禁止模拟写入或模拟重放                 |
| 404 NOT_FOUND             | 新请求引用的课堂不存在                         |
| 409 IDEMPOTENCY_CONFLICT  | 键已绑定不同载荷                               |
| 409 CLASSROOM_NOT_OPEN    | 采样时间在课堂时段外                           |
| 422 INVALID_RECORD_TIME   | 采样时间晚于服务端当前时间                     |
| 422 VALIDATION_ERROR      | 载荷、时间格式、表情、来源或请求键无效         |
| 503 UNAVAILABLE           | 未配置入库令牌或数据库连接不可用               |

所有响应禁止缓存，不回显原始输入、凭据或内部异常。教师只查询自己所授课堂的 AI 历史，学生个人历史不包含 AI；入库令牌不能调用用户历史。模拟记录默认不进入历史，只有隔离开发环境显式开启后才返回且保留标记。

## 验证

安装 `services/backend/requirements-dev.txt` 与 `services/ai/requirements.txt`，设置 MOOD_TEST_DATABASE_URL 指向有建库权限的 PostgreSQL 测试服务器，从 `services/backend` 运行 `../../.venv/bin/python -m pytest -q`。测试使用独立临时数据库，覆盖令牌隔离、字段校验、采样时段、阈值、过滤与接受幂等、并发、迁移保留与回填、数据库回滚，以及真实 HTTP 上报、丢失回执和服务重启。

从 `services/ai` 运行同一 pytest 命令，验证队列、回执校验、失败保留和退避行为。结构化上报链路使用合成采样输入并明确标记模拟，不代表真实模型、摄像头或 DeepSeek 推理效果已经验收；采集验证见 [摄像头说明](camera-api.md)。
