# 手动反馈与历史

正式后端使用 PostgreSQL 保存手动反馈、幂等键和审计。启动、账号和课堂初始化分别见 [数据库说明](backend-database.md)、[账号说明](backend-auth.md)、[课堂说明](backend-classrooms.md)。应用健康接口 stage 为 `ai-ingestion`；基础统计、实时看板和导出仍未开放，AI 接口见 [匿名 AI 入库](backend-ai-ingestion.md)。

## 提交

学生登录后，通过 `GET /api/sessions` 选择被安排的课堂。在服务端时段 `[startsAt,endsAt)` 内调用：

```http
POST /api/emoji
Authorization: Bearer <学生令牌>
Idempotency-Key: <本次操作的稳定键>
Content-Type: application/json

{"sessionId":"11111111-1111-4111-8111-111111111111","emotion":"CONFUSED"}
```

UUID 仅为格式示例，调用时替换为真实课堂编号。幂等键允许 1—100 个 ASCII 字母、数字及 `._:-`，建议每次主动操作生成 UUID。九种情绪均可用于手动反馈，`FOCUSED`、`CONFUSED` 不来自表情模型。

只接受 `sessionId`、`emotion`；用户编号、来源、时间、模拟标记和 AI 元数据不能由学生指定，额外字段返回 422。成功 data 为共享 EmojiRecord，包含记录编号、学生编号、课堂编号、情绪、MANUAL 来源、UTC 时间、null 置信度和 false 模拟标记，以及课堂与学生摘要。

服务端按用户、课堂的顺序获取锁，重新验证会话、学生身份和安排名单，再取当前 UTC 时间。等待锁不延长课堂有效期；同一课堂的名单替换、时间维护与提交互相协调。记录和 `EMOJI_MANUAL_SUBMIT` 审计同事务提交，数据库提交失败不会返回成功。

同一学生、同一键、相同载荷返回既有记录且不追加审计；同键不同载荷返回 409 `IDEMPOTENCY_CONFLICT`。不同学生的键互不影响。主动再次反馈使用新键，不覆盖先前记录。原请求成功后即使课堂结束或学生被移出名单，有效学生身份仍可用原键和原载荷重放；使用新键则重新检查名单和时段。

网络中断、超时、服务错误或无效成功回执可能意味着结果未知。客户端同页、同账号、同课堂、同选择重试复用原键，不自动重放；刷新、换号或更改选择前先查看历史核实。客户端只有收到与提交一致的有效 MANUAL 回执后才显示保存成功。

## 历史与权限

```http
GET /api/emoji/history?sessionId=<课堂编号>&source=MANUAL&from=2026-11-06T00:00:00Z&to=2026-11-07T00:00:00Z
Authorization: Bearer <用户令牌>
```

成功 data 为完整 EmojiRecord 数组，按 `recordedAt DESC,id DESC` 排序，不静默截断；空结果为 `[]`。过滤项为 `sessionId`、`userId`、`course`（课程 UUID）、`class`（课堂班级精确匹配）、`from`、`to`、`source`（MANUAL、AI、ALL，默认 ALL）。所有过滤与角色范围取交集；时间带时区并按实际时间比较，起点包含、终点不包含。非法或未知参数返回 422。

| 身份   | 可见范围                                                                  |
| ------ | ------------------------------------------------------------------------- |
| 学生   | 仅本人 MANUAL；显式其他 userId 或 AI 返回 403；移出名单后仍能查看本人历史 |
| 教师   | 实际任课 classroom.teacherId 对应课堂的历史，包括已移出名单学生及匿名 AI  |
| 管理员 | 全部历史，可进一步过滤                                                    |

显式课堂编号不存在返回 404，无权访问返回 403。学生当前被安排或在课堂已有本人手动记录才可显式查询；当前名单不决定既有记录的归属。课堂开始或已有记录后，课程、任课人和起止时间禁止修改，避免转移历史的授权范围。

每条正式记录附带 `classroom` 摘要 `{id,courseId,courseName,teacherId,teacherName,className,room,startsAt,endsAt}` 和 `student` 摘要 `{id,username,studentNo,realName,className,status}`；不包含完整名单、邮箱、密码、令牌或内部幂等信息。资料按当前授权范围读取，资料更正后摘要可变化。学生在“我的记录”选择“全部课堂”可查看已移出名单课堂的反馈，展示使用记录中的课堂摘要。

AI 的 userId 与 student 均为 null；保留 `inferenceProvider`、`confidenceKind` 和原始分数，DeepSeek 的 `self_reported` 不是准确率或校准概率。默认不返回 simulated 数据；仅隔离开发环境可配置 `MOOD_ALLOW_SIMULATED_AI=true` 并保留模拟标记。历史接口读取已有结构化记录，不接收图像；AI 写入使用独立的 [入库接口](backend-ai-ingestion.md)。

## 错误与验证

| 状态与业务码             | 含义                             |
| ------------------------ | -------------------------------- |
| 401 UNAUTHENTICATED      | 缺少、过期、撤销或失效身份       |
| 403 FORBIDDEN            | 非学生提交、未安排课堂或历史越权 |
| 404 NOT_FOUND            | 显式课堂不存在                   |
| 409 CLASSROOM_NOT_OPEN   | 新反馈不在课堂时段内             |
| 409 IDEMPOTENCY_CONFLICT | 同键载荷不同                     |
| 422 VALIDATION_ERROR     | 载荷、参数或幂等键不合法         |
| 503 UNAVAILABLE          | 数据库连接不可用                 |

成功与错误响应均禁止缓存。退出撤销当前会话，改密撤销全部会话；撤销后不能重放或查询历史。数据库故障与审计失败不暴露内部异常或凭据。

设置 `MOOD_TEST_DATABASE_URL` 后，在 `services/backend` 执行 `../../.venv/bin/python -m pytest -q`。测试创建独立临时 PostgreSQL 库，覆盖九种情绪、身份和名单、时间边界与锁等待、并发幂等、原子回滚、移出名单、全量历史、匿名与模拟来源、真实 HTTP 提交和服务重启持久性。客户端通过 `npm run test:client` 验证回执、重试键和历史摘要；构建及类型检查命令为 `npm run build`、`npm run typecheck`。
