# 账号认证与教师审批

正式后端通过 PostgreSQL 持久化用户、教师申请、登录会话及关键操作审计。账号注册、登录、本人信息、改密、注销、管理员用户目录和教师审批已实现；课堂、反馈、统计、导出及 AI 控制仍按各自接口状态开放。

## 运行与管理员初始化

先安装 `services/backend/requirements-dev.txt`，配置 `services/backend/.env` 并执行数据库迁移。账号功能使用已有 `001` 至 `004` 结构，无需重建数据库。

从仓库根目录执行：

```bash
PYTHONPATH=services/backend .venv/bin/python -m app.cli.bootstrap_admin --username admin --email admin@example.edu
```

PowerShell：

```powershell
$env:PYTHONPATH = 'services/backend'
.\.venv\Scripts\python.exe -m app.cli.bootstrap_admin --username admin --email admin@example.edu
```

命令从终端隐藏读取并确认密码，可附加 `--real-name`。容器使用：

```bash
docker compose exec backend python -m app.cli.bootstrap_admin --username admin --email admin@example.edu
```

自动化环境显式增加 `--password-stdin`，通过标准输入传入单行密码；不提供密码命令行参数。实际密码不写入命令示例、Git、环境变量示例或输出。初始化只在没有任何管理员时成功，使用数据库事务锁防止并发重复创建；存在管理员时失败，不修改密码，也不把已有学生或教师提升为管理员。新用户与 `ADMIN_BOOTSTRAP` 审计在同一事务提交。

启动方式、数据库配置和迁移命令见 [数据库说明](backend-database.md)。

## 接口与角色

成功响应均使用 `{code:"OK",message:"成功",data:...}`，注册、改密、注销的 data 为 null；错误 data 为 null。受保护请求使用 `Authorization: Bearer <用户令牌>`。

| 接口                                                   | 身份与行为                                                                      |
| ------------------------------------------------------ | ------------------------------------------------------------------------------- |
| `POST /api/auth/register`                              | 公开注册 STUDENT，或以 TEACHER 提交教师申请；不能指定 ADMIN、账号状态或密码哈希 |
| `POST /api/auth/login`                                 | 校验账号密码、启用状态与教师审批；成功返回 `{token,user}`                       |
| `GET /api/users/me`                                    | 返回当前用户资料，不包含密码哈希或会话摘要                                      |
| `PUT /api/auth/password`                               | `{oldPassword,newPassword}`；原密码正确且新旧不同，成功后撤销全部会话及关联票据 |
| `POST /api/auth/logout`                                | 撤销当前会话及关联票据，其他设备保持登录                                        |
| `GET /api/admin/users`                                 | 仅管理员；返回 User 数组，含可选学生资料与教师审批状态                          |
| `GET /api/admin/teacher-applications`                  | 仅管理员；返回 TeacherApplication 数组，按提交时间和编号倒序                    |
| `PUT /api/admin/teacher-applications/{application_id}` | 仅管理员；提交 `{decision:"APPROVED"或"REJECTED",reason?}`，返回更新后的申请    |

用户名去除首尾空白，长度 2—50，保留大小写并区分大小写；邮箱使用格式校验和域名规范化，唯一性遵循数据库保存值。新密码长度 8—128，不去除密码空白；登录与原密码输入长度为 1—128。可选学号去除首尾空白，非空时唯一。重复用户名或邮箱返回 409 ACCOUNT_EXISTS，学号重复返回 409 STUDENT_NO_EXISTS；不返回具体冲突字段的现有值。

所有认证成功响应和错误响应设置 `Cache-Control: no-store`。参数错误不会回显密码、令牌或请求原文；数据库连接失败返回 503 UNAVAILABLE，不返回连接字符串、SQL 或参数。

## 教师申请

注册 `role: TEACHER` 时，用户实际角色初始为 STUDENT，同时创建 PENDING 申请；仅可附加姓名，不能包含学生学号或班级。PENDING 和 REJECTED 用户不能登录。教师角色没有对应 APPROVED 记录时，同样不能登录。

管理员查询申请和用户目录核对资料后作出决策。只有 PENDING 且账号启用、角色仍为 STUDENT 的申请可以审核。批准在同一事务中更新申请、授予 TEACHER、撤销申请者已有会话及票据并写入审计；驳回保留 STUDENT，记录审核人、时间与原因并撤销会话。重复或并发冲突审核返回 409 CONFLICT；申请不存在返回 404 NOT_FOUND。审核失败时角色、申请和审计一起回滚。

申请审核接口不授予 ADMIN，也不提供自动重新申请。账号禁用状态与审批状态分离。原有数据库迁移认可的历史教师保持 APPROVED，审核人为空表示历史授权。

## 密码和会话

密码使用 Argon2id：内存 19456 KiB、迭代次数 2、并行度 1，盐长 16 字节且每次随机生成，哈希输出 32 字节。成功登录可重新哈希旧 Argon2 参数；损坏哈希及原有占位字符串不能通过验证。未知账号与错误密码均返回相同的 401 UNAUTHENTICATED 响应。

用户令牌包含 `usr_` 前缀和 32 字节随机值的 URL 安全编码；数据库只保存 SHA-256 摘要。AI 入库与 AI 控制令牌必须独立，不能使用 `usr_` 前缀；用户令牌不能调用 AI 入库。会话默认 8 小时，采用固定有效期，配置见 `MOOD_USER_SESSION_TTL_SECONDS`。

每次受保护请求都读取持久化会话并检查过期、撤销、账号启用状态和教师授权，进程重启后仍可验证未失效会话。缺失、伪造、过期、撤销或当前账号不可用时返回 401；登录时密码正确但账号禁用返回 403 ACCOUNT_DISABLED，教师申请未获准返回 403 TEACHER_APPROVAL_REQUIRED。没有所需角色返回 403 FORBIDDEN；原密码错误返回 403 INVALID_PASSWORD。

登录、改密和注销按用户行锁串行协调，避免旧密码并发登录在改密后留下有效会话。管理员审核固定用户锁顺序，并在事务内重新校验管理员会话和角色。注销与改密使已有一次性票据失效；票据发放与 WebSocket 实时连接仍待实现，当前 WebSocket 拒绝连接。

审计记录成功注册、教师申请、登录、退出、改密、审核及管理员初始化，只保存固定操作名、操作者、目标编号与时间，不保存密码、令牌或请求正文。相关写操作和审计共同提交，审计写入失败时操作整体回滚。

## 后续业务边界

未实现接口仍返回 501。学生可进入课堂、历史和手动提交接口的业务边界，但不能访问用户目录、审批、教师统计和导出；教师和管理员可以进入统计、看板的业务边界；课堂学生安排与 CSV 仅限管理员；手动反馈只限学生。角色允许不代表课堂数据范围已经完成，实际课堂和记录查询仍待实现，不能以空列表冒充成功。

## 验证

沿用 `MOOD_TEST_DATABASE_URL` 的独立 PostgreSQL 测试入口，命令见数据库说明。账号用例使用真实数据库和 Argon2，覆盖注册提权拒绝、唯一冲突、摘要存储、多设备退出、改密全撤销、失效和禁用、教师审批、并发初始化、并发审核、登录与改密竞争、审计失败回滚、命令输入及私密数据不回显。接口替身测试不作为真实权限验收。
