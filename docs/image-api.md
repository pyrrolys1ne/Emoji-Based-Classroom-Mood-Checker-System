# DeepSeek 图片表情分析

图片分析使用 DeepSeek 官方 `deepseek-flash` 识图接口，无需安装 DeepFace、OpenCV 或下载模型权重。服务对公开测试样本执行远程推理，与摄像头采集任务相互独立。

## 配置与样本

安装 `services/ai/requirements.txt` 中的基础依赖。复制 `services/ai/.env.example` 为同目录 `.env`，只在该服务端文件中填写 `DEEPSEEK_API_KEY`。服务自动读取此文件，已有进程环境变量优先；修改后重启 AI 服务。密钥不使用 `VITE_` 前缀，不发送至浏览器，也不提交到 Git。

在仓库根目录执行：

```powershell
$env:PYTHONPATH = 'services/ai'
.\.venv\Scripts\python.exe -m app.sample_cli download
```

下载清单位于 `services/ai/data/face-samples.json`，包含三张 NASA 公开人像的来源、作者和公有领域标记，以及一张程序生成的无人脸对照图。照片只下载至被 Git 忽略的 `.local/face-samples`；下载时限制文件大小、缩小至最长边 1024 像素、清除元数据并重新编码。程序生成对照图采用 CC0。样本用于接口与无脸场景检查，没有表情真值标注，也不构成模型评测数据集。

## 管理端与命令行

`AI_DATA_DIR` 可覆盖样本与报告根目录。容器镜像只包含样本清单，不打包已下载照片、报告或密钥；需要在容器运行环境单独配置和下载。

执行 `npm run dev:integration`，以管理员合成账号登录后，打开“AI 集成”页的“图片表情分析”。选择样本并勾选发送至 DeepSeek，点击“分析图片”。教师不能调用图片分析。页面展示类别、模型自评分和耗时；没有人脸时显示未检出，无法确定时保留未知结果。

命令行真实分析需显式启用远程发送：

```powershell
$env:PYTHONPATH = 'services/ai'
.\.venv\Scripts\python.exe -m app.sample_cli analyze --allow-remote-upload
# 只分析一张指定样本
.\.venv\Scripts\python.exe -m app.sample_cli analyze --image control-blank --allow-remote-upload
```

结构化输出保存在被忽略的 `.local/deepseek-image-report.json`。每张图片只发起一次请求；连接失败、余额不足、鉴权失败、限流和无效响应均明确报错，不自动重试付费推理。可在确认错误原因后手动重试。请求、图片内容、上游原始错误体与密钥不写入应用日志。

## 接口与边界

本页的公开样本分析与 [摄像头实验](camera-api.md) 是两个入口。摄像头实验通过独立启动参数明确允许发送实时帧，并配置有限次数与时长；同样不保存原始影像，但可将匿名结构化结果写入所选课堂。

管理员调用 `GET /api/admin/ai/vision` 获取配置状态和样本目录，调用 `POST /api/admin/ai/analyze-image` 提交 `{ "imageId": "portrait-01", "allowRemoteUpload": true }`。参考服务通过独立控制令牌转发到 AI 服务的 `/control/vision` 和 `/control/analyze-image`。正式后端尚未实现这些代理。

接口只接受清单内已下载样本的编号，不接受任意文件路径或远程 URL。AI 服务将清除元数据后的 JPEG 以内联 base64 发送至固定官方地址 `https://api.deepseek.com/chat/completions`，禁止 HTTP 重定向。上游使用 JSON 输出，严格校验类别、分数范围、字段与完成状态；不完整、越界或未知类别不作为成功返回。

结果包括 `provider`、`model`、`imageId`、`faces`、`elapsedMs`，以及 `confidenceKind: "self_reported"`、`calibrated: false`、`sampleOnly: true`、`persisted: false`。每个人脸包含 `label`、`score` 与系统 `emotion`；不确定类别对应 `emotion: null`。映射沿用七种基本表情，禁止推断“专注”“困惑”、身份或人口属性。

模型自评分未经校准，不能直接作为准确率、识别概率、心理状态或学习理解程度。样本分析不经过课堂上报队列，不写入课堂数据库，不影响统计图表。摄像头不会因图片分析而开启；摄像头可显式选择独立的本地模型或 DeepSeek 远程适配。公开样本存储不改变真实课堂原始影像默认不保存、不上传的约束。

## 依据

- [DeepSeek 官方识图说明](https://api-docs.deepseek.com/guides/vision/)
- [DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)
- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)
- 图片作者与授权页见样本清单的 `sourceUrl` 字段。
