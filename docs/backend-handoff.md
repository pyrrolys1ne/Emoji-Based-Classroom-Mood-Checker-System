# 后端联调交接说明

管理端已有登录适配、课堂安排、历史查询、实时看板、多维统计与 CSV；AI 服务已接通 DeepSeek 图片和摄像头推理、过滤、匿名上报与重试。当前链路使用 `services/integration` 和 SQLite；正式后端 `services/backend` 的业务接口仍为占位，需要补齐后切换到 PostgreSQL。

## 后端需要完成的工作

| 优先级 | 工作与接口                                                                      | 关键要求                                                                                                        |
| ------ | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| 1      | 账号与权限：注册、登录、改密、`GET /api/users/me`、退出登录                     | 密码加盐哈希；登录返回 `{token,user}`；管理员受控创建；教师仅访问所授课堂；退出后撤销会话                       |
| 1      | 基础业务：用户列表、课堂查询与学生安排、手动表情提交、历史查询                  | 使用真实数据库；查询按角色限定范围；安排校验有效学生；兼容现有前端字段                                          |
| 1      | AI 入库：`POST /api/ai/emoji-results`                                           | 独立服务令牌；持久化匿名记录；以 `Idempotency-Key` 唯一约束去重，同键不同载荷返回 409                           |
| 2      | 实时推送：`POST /api/auth/ws-ticket`、`WebSocket /ws/dashboard`、实时看板接口   | 一次性票据有效期 30 秒；按可见课堂范围通知刷新；退出后关闭连接                                                  |
| 2      | 多维统计与 CSV：`GET /api/admin/statistics`、`GET /api/admin/emoji/export`      | 支持课程、班级、时间筛选；时间采用 `[from,to)`；全量聚合，不能只统计当前页；导出防公式注入                      |
| 2      | AI 管理代理：`/api/admin/ai/status`、`start`、`stop`、`vision`、`analyze-image` | 仅限管理员，转发至 AI 服务的 `/control/*`；支持 `camera-api` 及采样上限；服务令牌和 DeepSeek 密钥不发送到浏览器 |

## 必须保持的契约

- 统一响应为 `{code,message,data}`，成功 `code: "OK"`；字段用小驼峰，时间戳带时区。当前列表的 `data` 是数组；引入分页须同步前端仓储与服务端统计。
- AI 请求包含 `sessionId`、`emotion`、`confidence`、`recordedAt`、`deviceId`、`source: "AI"`；兼容 `simulated`、`inferenceProvider`、`confidenceKind`。DeepSeek 必须保留 `confidenceKind: "self_reported"`，不能将自评分当作准确率；不接收原始图片或视频。正式环境默认拒绝模拟数据。
- AI 入库成功返回 `data: {accepted:true,created,record}`；低于阈值返回 `data: {accepted:false,reason:"LOW_CONFIDENCE"}`。数据库提交成功后才能确认接受；重复上报不得重复入库。
- 按顺序核对数据库脚本 `infra/database/001_initial.sql`、`002_model_emotions.sql`、`003_inference_metadata.sql`，保留九种系统情绪枚举；“专注”“困惑”只用于手动反馈。

## 联调交付与通过标准

提供 OpenAPI、数据库初始化及迁移方法、环境变量示例、管理员初始化方式和管理员／教师／学生测试账号；实际密码与令牌单独交付，不提交仓库。

优先打通“真实登录 → 课堂与历史查询 → AI 入库 → 看板自动刷新”，再完成统计、导出和全部角色验收。通过标准：管理员能安排和导出，教师不能越权，学生能提交并查看个人历史，AI 重复上报不重入库，重启后数据保留，统计与导出结果一致。

接口细节以 [API 契约](api-contract.md) 的增量版本为准；可参考 `services/integration/integration_app` 的响应和测试，但不能将合成账号与参考认证方式用于正式后端。现有 AI 推理和管理端页面无需重写，接口调整须同步契约与调用方。
