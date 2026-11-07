# 后端联调验收清单

本清单核对正式后端的业务、权限、持久化与调用契约。接口索引、环境配置和已验证基线见 [后端交付说明](backend-handoff.md)，完整字段见 [API 契约](api-contract.md) 与运行时 `/openapi.json`。

## 测试准备

使用独立 PostgreSQL 测试库和合成账号，准备一名管理员、两名已批准教师、两名学生，以及分属不同任课教师的课堂与名单；另保留未审核教师申请。管理员通过有效一次性邀请码注册，或由受控 CLI 初始化；普通学生／教师注册不能创建管理员。课堂时段覆盖正常提交场景，课前和课后场景单独设置。

用户令牌、AI 入库令牌和 AI 控制令牌分别配置；正式 API 模式关闭演示回退。模拟 AI 仅在独立测试库允许，原始影像不进入接口或测试产物。每个场景注明来源、课堂、时间范围和预期数据集，避免把不同请求时刻的统计差异当作错误。

管理员邀请码的过期、重复使用、并发消费和审计回滚由 `test_admin_registration.py` 覆盖。登录与统计筛选的 SQL 注入专项分别位于 `test_accounts.py` 和 `test_statistics.py`。

## 功能与边界核对

以下场景在交付基线的自动化中已通过。对其他调用环境复核时，分别记录通过、失败或未执行，不能直接沿用基线结论。

| 编号 | 场景与通过条件                                                                                                            | 自动化入口                                                                                                 |
| ---- | ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| B01  | 空库顺序执行 001—008；重复迁移不改数据，旧库升级保留数据，未知结构和校验和异常明确拒绝                                    | `test_database.py`、`test_realtime_migration.py`                                                           |
| B02  | 学生注册登录成功；教师申请未经审批不能登录，批准后获得 TEACHER；公开指定 ADMIN 被拒绝                                     | `test_accounts.py`、`test_contract.py`                                                                     |
| B03  | 伪造、过期、撤销会话被拒绝；注销只撤销当前设备，改密撤销全部设备；响应不含密码或令牌摘要                                  | `test_accounts.py`、`test_system.py`                                                                       |
| B04  | 学生只获取被安排课堂，名单摘要只含本人；教师按课堂实际任课人授权；其他角色不能写课程、课堂、名单或学生资料                | `test_classrooms.py`                                                                                       |
| B05  | 已开始或已有记录的课堂不能调整课程、教师和时段；课程默认教师变化不转移已有课堂权限；无效名单替换保留原数据                | `test_classrooms.py`                                                                                       |
| B06  | 仅名单内学生在课堂时段提交；服务端确定用户、来源和时间；同键同载荷重试只保留一条，同键不同载荷返回冲突                    | `test_feedback.py`、`system-browser.mjs`                                                                   |
| B07  | 学生不能互查历史，教师不能跨任课课堂查询；移出名单后既有本人记录保留；AI 匿名，模拟记录默认隐藏                           | `test_feedback.py`、`test_ai_ingestion.py`                                                                 |
| B08  | AI 只接受独立入库令牌、七种表情、有效分数和带时区采样时间；低分过滤与接受均保存稳定回执，并发和重复请求不重入库           | `test_ai_ingestion.py`                                                                                     |
| B09  | 历史、统计和 CSV 使用相同授权与筛选交集；`[from,to)`、来源、时区及跨日边界正确；分布、趋势、分组取全量且合计一致          | `test_statistics.py`                                                                                       |
| B10  | CSV 仅管理员可导出；10 行页面不截断全量文件；BOM、引号、逗号、换行和公式防护正确，提供方与自评分类型保留                  | `test_statistics.py`、`system-browser.mjs`                                                                 |
| B11  | 实时票据短期、一次性且跨进程不可重放；Origin 与显式课堂范围正确；通知不含完整记录；注销、到期和身份变化后关闭             | `test_realtime.py`                                                                                         |
| B12  | AI 状态、启动、停止与公开样本代理仅管理员可用；固定上游与独立控制令牌；参数和回执校验、敏感字段过滤、超时未知结果正确     | `test_ai_control.py`                                                                                       |
| B13  | 账号、课堂、反馈和 AI 接受写入与审计原子提交，异常回滚；AI 控制按 REQUEST 与结果审计，外部操作结果未知时不宣称已回滚      | `test_accounts.py`、`test_classrooms.py`、`test_feedback.py`、`test_ai_ingestion.py`、`test_ai_control.py` |
| B14  | 后端重启保留记录、有效会话和未过期未消费票据；AI 断网保留结构化队列，重启不自动采集，显式恢复后稳定键补传                 | `test_feedback.py`、`test_ai_ingestion.py`、`test_realtime.py`、`test_system.py`                           |
| B15  | 同一手动记录可在学生历史、任课教师和管理员 CSV 中核对编号；前端失败不显示保存，丢失回执重试不重复，实时变化后刷新授权数据 | `system-browser.mjs`、`test_system.py`                                                                     |

`test_*.py` 单元及接口用例位于 `services/backend/tests/`；系统脚本 `test_system.py`、`system-browser.mjs` 位于 `scripts/`。B14 的 AI 队列只使用合成结构化输入，不代表真实模型采集通过。容器代理和备份恢复的附加验证见 [系统验收](system-acceptance.md)，不计作模型或目标主机验证。

## 错误处理核对

调用方同时检查 HTTP 状态和业务 code，使用稳定 code 分支，不依赖 message 文案。下表为常见错误，完整语义见各接口专题。

| HTTP / 业务码                                                                                                        | 含义与处理                                                                                   |
| -------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 401 `UNAUTHENTICATED`                                                                                                | 用户会话失效时清理身份并重新登录；AI 入库时核对独立服务令牌，不能改用用户令牌                |
| 403 `FORBIDDEN`                                                                                                      | 角色或数据范围拒绝，提示无权限；不扩大筛选或改用演示数据                                     |
| 403 `TEACHER_APPROVAL_REQUIRED` / `ACCOUNT_DISABLED`                                                                 | 登录时申请未获准或账号禁用，停止进入业务页面                                                 |
| 403 `INVALID_PASSWORD`                                                                                               | 改密原密码错误，保留当前登录态并提示修正                                                     |
| 403 `SIMULATED_AI_DISABLED`                                                                                          | 当前环境禁止模拟写入或重放，保持正式与测试环境隔离                                           |
| 404 `NOT_FOUND` / `AI_SAMPLE_NOT_FOUND`                                                                              | 课堂、资源或公开样本不可用，核对所选资源，不伪造成功                                         |
| 409 `ACCOUNT_EXISTS` / `STUDENT_NO_EXISTS`                                                                           | 注册或资料唯一性冲突，提示修正输入                                                           |
| 409 `IDEMPOTENCY_CONFLICT`                                                                                           | 同一操作键对应不同载荷，核对原操作与历史，不静默换键重复写入                                 |
| 409 `CLASSROOM_NOT_OPEN` / `CLASSROOM_LOCKED`                                                                        | 提交或采样时段不符，或课堂关键字段已锁定，按课堂状态处理                                     |
| 422 `VALIDATION_ERROR` / `INVALID_RECORD_TIME` / `INVALID_STUDENT` / `INVALID_TEACHER` / `AI_CONFIGURATION_REJECTED` | 请求字段、采样时间、账号引用或上游配置无效，修正后再提交                                     |
| 503 `UNAVAILABLE`                                                                                                    | 数据库不可用或 AI 入库令牌未配置；结果未确认时先核对，手动反馈与 AI 上报重试保持原幂等键     |
| 503 `AI_UNAVAILABLE`                                                                                                 | AI 控制未配置或不可连接，核对服务状态和后端连接配置                                          |
| 409 `AI_BUSY` / 429 `AI_RATE_LIMITED`                                                                                | AI 忙碌或上游限流，核对状态与接口提示，不自动重放控制或付费调用                              |
| 502 `AI_INVALID_RESPONSE` / `AI_UPSTREAM_AUTH` / `AI_UPSTREAM_ERROR`、504 `AI_TIMEOUT`                               | 上游回执、认证、服务错误或超时异常；控制与付费请求可能已执行，先核实状态，不清除正常用户会话 |
| 500 或 503 `AI_OPERATION_UNCONFIRMED`                                                                                | 外部操作与审计未共同确认，结果未知，不能宣称安全失败或自动重试                               |

AI 低分过滤使用 HTTP 200 和 `accepted:false` 回执，不是传输失败。CSV 失败是统一 JSON，不能将错误正文下载成成功文件。WebSocket 的 1008 表示身份、来源、范围或协议拒绝，1011 表示服务端检查失败；重连需新票据。

## 复现命令

从仓库根目录执行，先安装后端开发与 AI 基础依赖。测试账号须有建库权限；后端测试逐例创建并清理随机临时库，不清空环境变量指向的数据库。

```bash
export MOOD_TEST_DATABASE_URL='postgresql+psycopg://<测试账号>:<测试密码>@127.0.0.1:5432/postgres'
(cd services/backend && ../../.venv/bin/python -m pytest -q)
```

未设置变量时真实数据库用例会明确跳过，这种结果不能认定 B01—B14 全部通过。系统验收需要 Node.js 依赖和 Playwright Chromium，缺少测试数据库配置时直接失败：

```bash
npm ci
npx playwright install chromium
npm run test:system
```

PowerShell 环境变量使用 `$env:MOOD_TEST_DATABASE_URL = '...'`，Python 路径使用 `.venv\Scripts\python.exe`。系统脚本自动选择仓库虚拟环境，可用 `MOOD_TEST_PYTHON` 指定解释器。更多运行方式与产物说明见 [系统验收](system-acceptance.md)。

## 问题复现与验收结论

问题记录应包含代码或契约版本、B 编号、请求方法与路径、脱敏请求字段、角色与课堂范围、带时区的时间条件、HTTP 状态与业务码、预期与实际，以及是否发生重试或服务重启。反馈未知结果时说明是否已查历史、是否复用了原幂等键。不要附密码、完整访问令牌、服务令牌、密钥或原始影像。

后端验收结论应分别列出功能与边界通过项、失败项、未执行项，并附可复核的测试或 CI 证据。真实模型效果、摄像头设备、DeepSeek 实际调用、目标主机部署和真机兼容保持独立结论，不将结构化模拟通过转换为这些项目通过。
