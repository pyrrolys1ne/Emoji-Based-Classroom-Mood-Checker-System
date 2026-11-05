# 后端数据库与配置

正式后端使用 PostgreSQL、SQLAlchemy 模型与顺序 SQL 迁移。业务服务通过 `app.db.session.transaction` 显式包围事务，提交完成后才能返回写入成功；异常时自动回滚。运行数据库和连接凭据不进入版本库。

## 初始化与升级

安装 `services/backend/requirements-dev.txt`，配置 `services/backend/.env` 的 `MOOD_DATABASE_URL`。迁移账号需要库内建表、建类型、修改结构权限；接管旧库还需要创建验证 schema 的权限。从仓库根目录执行：

```bash
PYTHONPATH=services/backend .venv/bin/python -m app.db.migrate
```

PowerShell：

```powershell
$env:PYTHONPATH = 'services/backend'
.\.venv\Scripts\python.exe -m app.db.migrate
```

容器方式执行 `docker compose up --build -d`。`migrate` 服务在数据库就绪后执行，成功后才启动后端。更新已有环境时执行 `docker compose run --rm migrate`；命令失败时不要继续更新后端。SQL 文件不再通过数据库镜像的空卷初始化钩子执行，空库与已有数据卷使用同一迁移入口。

迁移按 `infra/database` 中连续的三位编号顺序执行，每个文件及其版本记录在同一事务提交。`schema_migration` 保存版本、文件名、SHA-256 和执行时间；校验前统一 UTF-8 BOM 与换行，兼容 Windows 和 Linux。重复运行跳过已有版本；校验和变化、未知版本、缺失编号或并发迁移会明确失败。修改结构应新增 SQL，不修改已执行文件。升级前备份数据库；此入口只支持向前升级，恢复由备份完成。

原有 `001_initial.sql`、`002_model_emotions.sql`、`003_inference_metadata.sql` 保持原样。尚无版本表的旧库，只有列、枚举、主外键、唯一约束、检查约束及索引与其中一个完整版本一致时才会自动接管，再执行后续文件。结构比较使用事务内临时验证结构，不读取业务数据，不遗留验证表。混用其他表或手动改动过结构的旧库需要先核对，不能通过清空数据绕过验证。

新增 `004_backend_foundation.sql` 保留旧记录并增加：

| 结构                                             | 用途                                                                      |
| ------------------------------------------------ | ------------------------------------------------------------------------- |
| `app_user.student_no`、`real_name`、`class_name` | 学号、姓名、所属班级；旧账号允许为空，非空学号唯一                        |
| `teacher_application`                            | 独立记录 `PENDING`、`APPROVED`、`REJECTED` 和审核信息；不混用账号禁用状态 |
| `user_session`                                   | 存放访问令牌的 SHA-256 摘要、有效期和撤销时间，不保存可复用明文令牌       |
| `ws_ticket`                                      | 绑定登录会话、有效期不超过 30 秒的一次性票据，记录消费时间                |
| `emoji_record.simulated`                         | 标记模拟 AI 输入，默认 false；正式服务默认拒绝模拟入库                    |
| `emoji_record.idempotency_key`、`request_hash`   | 稳定请求键和规范化请求摘要，成对存在；历史记录允许同时为空                |

AI 幂等键在 AI 来源内唯一，手动幂等键按学生隔离，与 AI 互不冲突。AI 记录约束匿名用户、有效设备、七种基本表情及提供方名称；DeepSeek 保留原有 `self_reported` 限制。旧库已有教师通过迁移保留授权并生成已批准记录，审核人为空表示历史授权；新增申请须通过受控审核流程。旧数据若违反新增约束，当前迁移会回滚并停止，不会自动删除或修改记录。

`app.db.models` 与 SQL 结构保持一致；运行服务不调用 `create_all`，以免绕过迁移。

## 配置

后端读取 `services/backend/.env`，进程环境变量优先。连接字符串必须使用 `postgresql+psycopg` 并指定数据库；URL 中的密码含特殊字符时需要 URL 编码。

| 环境变量                        | 默认值                  | 约束与用途                                                  |
| ------------------------------- | ----------------------- | ----------------------------------------------------------- |
| `MOOD_DATABASE_CONNECT_TIMEOUT` | 2                       | 连接超时秒数，1—60                                          |
| `MOOD_DATABASE_POOL_SIZE`       | 5                       | 常驻连接数，1—20                                            |
| `MOOD_DATABASE_MAX_OVERFLOW`    | 5                       | 额外连接数，0—50                                            |
| `MOOD_DATABASE_POOL_TIMEOUT`    | 10                      | 获取连接超时秒数，1—60                                      |
| `MOOD_USER_SESSION_TTL_SECONDS` | 28800                   | 用户会话时长，300—604800 秒                                 |
| `MOOD_WS_TICKET_TTL_SECONDS`    | 30                      | 一次性票据时长，1—30 秒                                     |
| `MOOD_AI_SERVICE_TOKEN`         | 空                      | AI 入库令牌；空值禁用入库认证                               |
| `MOOD_AI_CONTROL_TOKEN`         | 空                      | 管理代理使用的控制令牌，须匹配 AI 服务的 `AI_CONTROL_TOKEN` |
| `MOOD_AI_BASE_URL`              | `http://127.0.0.1:8001` | 服务端 AI 地址，不能包含凭据、查询参数或片段                |
| `MOOD_AI_MIN_CONFIDENCE`        | 0.5                     | 入库过滤阈值，有限数值且在 0—1 之间；不代表准确率           |
| `MOOD_ALLOW_SIMULATED_AI`       | false                   | 仅限隔离开发环境显式开启                                    |

用户令牌、AI 入库令牌和 AI 控制令牌独立，AI 令牌不能使用用户令牌保留前缀 `usr_`。会话认证、撤销与教师审批已接入上述结构，管理员初始化见 [账号说明](backend-auth.md)。AI 入库仅有服务令牌与参数验证，过滤配置尚未接入正式业务。`/api/ready` 仅检查数据库连通性，不证明已迁移或全部业务可用。

## 验证

```bash
cd services/backend
../../.venv/bin/python -m pytest -q
```

设置 `MOOD_TEST_DATABASE_URL` 可运行真实 PostgreSQL 用例，测试连接账号需要创建数据库权限。每个用例创建并清理独立临时库，不清空该变量指向的数据库；未设置时明确跳过。CI 使用独立 PostgreSQL 17 服务执行这些测试。

覆盖空库初始化、原有三个版本升级与数据保留、重复迁移、未知结构拒绝接管、校验和、失败回滚与重试、迁移锁、ORM 结构一致性、事务提交回滚、学号唯一性、并发幂等约束、AI 校验和票据时间约束。模型及约束测试不代表尚未实现的业务接口已通过验收。
