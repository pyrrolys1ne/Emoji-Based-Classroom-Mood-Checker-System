# 总体架构与修改版 MVC

项目采用 npm workspaces 单仓库与独立 Python 服务，方便四人按边界协作。用户是组长，负责管理端与 AI 集成，其余负责人未指定。

```mermaid
flowchart TD
  A[学生客户端 React 可替换为 Android] -->|REST JSON| API[后端 Controller]
  B[管理端 View] --> C[管理端 Controller Hook]
  C --> M[管理端 Model 统计与规则]
  C --> R[管理端 Repository]
  R -->|演示模式| DEMO[浏览器演示数据]
  R -->|API 模式 REST JSON| API
  AI[独立 Python AI 服务] -->|独立服务令牌| API
  API --> S[Service 业务层]
  S --> DBR[Repository 数据层]
  DBR --> PG[(PostgreSQL)]
```

管理端 `views` 负责展示，`controllers` 负责加载、状态与交互编排，`models` 负责领域类型使用、统计与导出规则，`repositories` 隔离演示和 API 数据源。后端控制器不直接访问数据库，按服务、仓储分层；当前健康检查已走完整分层，业务服务明确标为待实现。

共享情绪枚举和前端类型位于 `packages/contracts`；后端 Pydantic 模型与 Swagger 提供接口扩展点。字段采用 JSON 小驼峰，数据库使用蛇形命名，时间戳要求携带时区。前端演示编号为可读字符串，正式接口使用 UUID，切换 API 时不能发送演示编号。

后续实现须完成密码加盐哈希、真实身份校验与 RBAC、教师所授课程限制、学生个人记录范围、服务令牌隔离、CSV 注入防护、参数校验和 AI 匿名化。当前 UI 演示与占位接口不代表这些业务能力已经完成。

AI 侧仅保留结构化情绪结果，默认不保存视频、人脸图像或生物特征；“专注”“困惑”等是初始界面枚举，模型能力与课堂心理含义之间的映射需要验证并记录局限性。

v0.2 另增独立本地联调服务 `services/integration`，提供合成账号、角色范围、SQLite 结构化结果持久化、一次性 WebSocket 票据和 AI 控制代理。它与正式后端分别运行；前端通过同一接口适配层选择演示、联调或正式 API，不能将参考服务作为线上后端。真实模型映射七种表情，“专注”“困惑”仅保留给手动反馈。
