# 客户端运行与维护

客户端提供学生注册、登录、课堂反馈、个人历史、改密和退出，以及教师所授课堂历史和整体情绪分布。界面适配桌面和手机，演示与真实 API 数据独立。

## 启动

使用 Node.js 24 或仓库声明的兼容版本，在仓库根目录执行：

```sh
npm ci
npm run dev:client
```

打开 http://127.0.0.1:5174。默认是明确标识的演示模式，登录页可体验学生或教师。合成账号为 student-a、student-b、teacher-a、teacher-b，演示密码均为 `classroom-demo-2026`，只供本地演示，不是正式用户凭据。

演示数据保存在本站浏览器 localStorage 的 `mood-client-demo-v2`，登录凭据保存在 sessionStorage 的 `mood-client-auth-demo`。演示用户密码以独立盐和 PBKDF2 哈希保存，不存明文；这不构成正式身份认证。仅在需要重置演示时，通过浏览器开发工具删除该演示键并退出登录，不清除本站其他数据。

演示新学生自动安排到首节演示课堂；教师申请保存为未激活，不能自行获得教师权限。已有演示教师用于页面体验，演示没有审批后台。旧版 mood-client-demo-v1 数据保留但不再读取，避免沿用旧的未审核教师身份；升级后需重新登录并使用新的演示数据。当前演示课堂保持较长开放期，历史课堂用于验证结束后不可提交。

多个仓储实例在同一页面内串行操作；支持 Web Locks 的浏览器还协调同源标签页。无 Web Locks 时，演示模式不保证跨标签页并发写入，正式数据一致性由后端实现。

## 真实 API 配置

复制 apps/client/.env.example 为同目录 .env.local，将 `VITE_DATA_MODE` 设置为 `api`，按环境配置其他项后重启开发服务器。

| 变量                  | 默认值                | 用途                                             |
| --------------------- | --------------------- | ------------------------------------------------ |
| VITE_DATA_MODE        | demo                  | 仅接受 demo 或 api；无效值停止显示业务页面       |
| VITE_API_BASE_URL     | /api                  | 浏览器请求前缀；可使用同源反向代理               |
| VITE_API_PROXY_TARGET | http://127.0.0.1:8000 | 仅 Vite 开发代理目标，部署时配置对应的反向代理   |
| VITE_ADMIN_URL        | http://127.0.0.1:5173 | 教师进入管理端的地址；不传递访问令牌，可再次登录 |

VITE 变量会进入浏览器代码，只能填写公开配置，不能填写用户、AI 服务或第三方 API 密钥。生产部署须配置真实 API 与管理端地址，不能沿用开发回环地址；管理端入口只允许 HTTP／HTTPS，带用户名或密码的 URL 被拒绝。

API 登录态使用独立的 `mood-client-auth-api` 会话键，刷新时通过 `/api/users/me` 核对身份；演示账号与数据不会被发送到真实 API。401 清理登录态和个人数据，403 显示无权限，未实现、离线及坏响应保持失败状态。

手动提交只发送 `{sessionId,emotion}`。写请求不自动重试，收到服务端确认后刷新历史；网络中断可能出现结果未知，应先查历史再决定是否重试。提交期间锁定课堂选择和页面导航。退出会立即清理本地状态，服务端注销失败另行提示；改密成功后本设备重新登录，不承诺其他设备已被后端注销。

正式后端仍需提供身份、课堂范围、持久化、教师角色授予及全部业务能力。需要的接口、合成测试数据及未确定规则见 [客户端对接约定](client-integration.md)。演示数据不会同步到管理端。

## 架构

```text
src/views/             页面和展示组件，不直接发送业务请求
src/viewmodels/        登录与课堂状态、取消、并发及失效处理
src/models/client.ts   客户端接口、页面 Props 和业务边界
src/repositories/      API 适配、响应校验、独立演示数据
src/App.tsx            数据源选择和页面组合
src/__tests__/         组件与应用状态测试
e2e/                  浏览器流程、响应式、无障碍及受控 HTTP 测试
```

共享情绪、User、ClassSession、EmojiRecord、AuthSession 来自 packages/contracts。教师基础统计使用候选的 `{total,distribution}`，要求九种情绪的非负整数分布与 total 一致；正式后端确认后同步合同，不能静默丢字段或用分页历史替代全量统计。

## 检查与构建

在仓库根目录执行：

```sh
npm run typecheck
npm run test:client
npm run build
```

首次浏览器测试安装：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.local/browsers'
npm exec -- playwright install chromium firefox
npm run test:e2e --workspace @mood/client
```

macOS／Linux 可用 `PLAYWRIGHT_BROWSERS_PATH="$PWD/.local/browsers" npm exec -- playwright install chromium firefox`。配置默认使用仓库 .local/browsers，不修改用户已有浏览器配置。

本地下载受限时，可设置 `PLAYWRIGHT_CHROMIUM_CHANNEL=msedge` 或 chrome，使用已安装浏览器的独立测试实例；Firefox 项目仍需要相应的 Playwright 浏览器。CI 安装指定版本的 Chromium 和 Firefox。测试服务器占用 5184（演示）和 5185（API），不复用正在运行的同端口服务。

```powershell
$env:PLAYWRIGHT_CHROMIUM_CHANNEL = 'msedge'
npm run test:e2e --workspace @mood/client -- --project=chromium --project=mobile --project=api-chromium
```

浏览器截图、失败追踪和报告位于 apps/client/test-results 与 apps/client/playwright-report，均忽略提交。截图测试检查 1440×900、390×844 和 320 像素窄屏；手机视口不是实际手机设备验证。完整用例和真实联调通过标准见 [验收清单](client-acceptance.md)。
