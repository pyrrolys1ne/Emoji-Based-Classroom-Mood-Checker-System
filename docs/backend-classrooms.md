# 课程课堂与学生安排

正式后端提供课程默认教师、课堂实际任课人、学生资料和安排名单的持久化管理。管理员维护这些数据；教师只查询自己所授课堂，学生只查询被安排课堂。账号认证与教师审批见 [账号说明](backend-auth.md)。

## 数据库升级

沿用 `app.db.migrate` 命令升级至 `005_classroom_management.sql`，不修改或重放历史 SQL。新增 `class_session.teacher_id`，按迁移时课程的 `teacher_id` 回填，并建立非空外键与教师时间索引。后续修改课程默认教师不会改写已创建课堂的任课人。

新增 `classroom_import` 保存初始化批次编号、管理员编号和时间。唯一编号用于拒绝重复或并发重复提交，不保存原始文件和密码。批次记录与课程、课堂、名单和审计共同提交，任何一步失败都会回滚。

## 接口

成功响应均使用 `{code:"OK",message:"成功",data:...}`。读取列表的 data 为数组，不静默截断；所有接口要求真实登录并返回 `Cache-Control: no-store`。

| 接口                                             | 身份     | 请求与返回                                                                |
| ------------------------------------------------ | -------- | ------------------------------------------------------------------------- |
| `GET /api/admin/courses`                         | 管理员   | 返回 Course 数组，按名称、编号排序                                        |
| `POST /api/admin/courses`                        | 管理员   | `{name,teacherId}`，返回新 Course                                         |
| `PUT /api/admin/courses/{course_id}`             | 管理员   | 同上，完整修改名称和默认教师，返回 Course                                 |
| `GET /api/sessions`                              | 三类角色 | 按实际范围返回 ClassSession 数组，按开始时间、编号排序                    |
| `POST /api/admin/sessions`                       | 管理员   | `{courseId,startsAt,endsAt,room,className,teacherId?}`，返回 ClassSession |
| `PUT /api/admin/sessions/{session_id}`           | 管理员   | 同上，返回更新后的 ClassSession                                           |
| `POST /api/admin/sessions/{session_id}/schedule` | 管理员   | `{userIds:[UUID]}`，完整替换名单，成功 data 为 null                       |
| `PUT /api/admin/users/{user_id}/student-profile` | 管理员   | 可选 studentNo、realName、className，返回 User                            |

Course 为 `{id,name,teacherId}`。默认教师和新指定的课堂教师必须是启用且已经 APPROVED 的 TEACHER，不能使用管理员、学生、待审批或禁用账号；不符合要求返回 422 INVALID_TEACHER。不存在的课程、课堂和学生返回 404 NOT_FOUND。

新建课堂省略 teacherId 时使用课程当前默认教师；修改课堂省略 teacherId 时保留课堂当前任课人。显式 null 返回 422。任课教师可以与课程默认教师不同。课堂结束必须晚于开始，时间必须带时区；教室和班级不能为空，最长 100 字符。课程默认教师或课堂教师在写入前并发变化且请求依赖旧值时返回 409 CONFLICT，由调用方重新读取后提交。

课堂已经开始，或已有任何情绪记录时，不允许修改 courseId、teacherId、startsAt、endsAt，返回 409 CLASSROOM_LOCKED；可在其他参数合法时更正教室和班级。未来且无记录的课堂允许显式调整任课人与课程，后续查询立即按新任课范围返回。修改和名单替换均保留已有记录，不移动、覆盖或删除情绪记录。

## 课堂范围与名单

ClassSession 保留既有字段，并增加实际任课 `teacherId` 与 `scheduledStudents`。名单摘要字段为 `{id,username,studentNo,realName,className,status}`，不含邮箱、密码、哈希或令牌。

- 管理员获取全部课堂和名单；教师按 `class_session.teacher_id` 获取所授课堂及对应名单。
- 学生必须在当前安排名单中，才能获取课堂；响应中的 scheduledUserIds 和 scheduledStudents 仅包含该学生本人，不返回同学资料。
- 范围与名单在同一 SQL 查询读取，避免多次查询间教师或名单变化导致读取其他范围。请求中的额外 teacherId、userId 等参数不能扩大服务端范围。
- 新建课堂的名单为空；学生注册或修改所属班级不会自动加入任何课堂，必须由管理员安排。

名单替换最多接收 500 个 UUID，重复值去重，空数组清空名单。只能新安排启用且符合登录条件的 STUDENT；未审核或驳回的教师申请者不能当作学生安排。无效账号返回 422 INVALID_STUDENT，原名单保持不变。旧安排的用户即使后来禁用，其资料仍可在授权名单中显示 DISABLED；新安排必须重新通过有效性校验。

学生资料请求至少包含一个字段，省略保留原值，显式 null 清空，非空值去除首尾空白。非空学号全局唯一，重复返回 409 STUDENT_NO_EXISTS；不得修改 role、status、email 或密码。只能维护符合学生身份的账号，允许更正禁用学生的资料但不会启用账号。修改学号冲突时其他字段一并回滚。

共享 TypeScript 的 teacherId 和 scheduledStudents 保持可选，以兼容独立演示及联调服务；正式 ClassSession 响应包含这两项。客户端 API 仓储会验证名单字段与编号列表一致。新增课程管理页面不属于这些接口本身。

## 初始化课程与课堂

初始化文件结构见 [合成示例](examples/classrooms.json)。先注册所需学生、申请并批准教师，再调整文件中的账号引用、时间和 importId。示例不包含密码，命令不自动创建账号、提升教师权限或生成情绪记录。

从仓库根目录执行：

```bash
PYTHONPATH=services/backend .venv/bin/python -m app.cli.import_classrooms --username admin --file docs/examples/classrooms.json
```

PowerShell：

```powershell
$env:PYTHONPATH = 'services/backend'
.\.venv\Scripts\python.exe -m app.cli.import_classrooms --username admin --file docs/examples/classrooms.json
```

命令隐藏读取现有管理员密码。自动化环境可显式使用 `--password-stdin`，通过标准输入提供单行密码；不提供密码命令行参数。命令直接验证启用的管理员账号，不发放登录令牌。输出仅包括批次编号与创建数量，错误不回显密码、原始 JSON 或数据库参数。

文件使用 UTF-8，可含 BOM，大小不超过 1 MiB。课程最多 100 门，课堂最多 500 节，每节最多安排 500 个学生用户名，引用账号合计不超过 2000 个。courses 的 key 唯一，sessions 的 courseKey 必须引用本批次课程；课堂可选 teacherUsername 覆盖默认教师。用户名沿用区分大小写的账号规则。

importId 是调用方提供的 UUID，整批只允许成功提交一次。重复或并发重复提交返回 IMPORT_ALREADY_EXISTS，不创建第二套数据；不同编号表示不同批次，不按课程名称覆盖已有数据。失败批次不留下编号，修正后可以用相同编号重试。需要修改已有课程或课堂时使用管理接口。

## 验证与边界

关键操作写入固定动作名的审计，与业务同事务提交。测试使用真实 PostgreSQL，覆盖三类角色隔离、学生名单隐私、课程换教师不转移历史课堂、未来课堂调整、时间顺序、无效安排拒绝、名单与导入的并发、唯一冲突、事务回滚、命令执行及数据保留。迁移继续覆盖空库、旧库升级和重复运行。

手动反馈、个人和课堂历史、匿名 AI 入库已接入正式后端，分别见 [反馈说明](backend-feedback.md) 和 [AI 入库说明](backend-ai-ingestion.md)。统计与 CSV 已接入全量记录，见 [统计导出说明](backend-statistics.md)；名单、课程及相关学生资料变更通过课堂版本通知可见用户刷新，实时与 AI 控制见 [实时说明](backend-realtime-ai.md)。
