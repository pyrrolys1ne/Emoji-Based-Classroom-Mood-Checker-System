import { useEffect, useState } from 'react';
import { emotions, type AIConfig, type AIStatus, type ClassSession } from '@mood/contracts';
import { isDemo, request } from '../repositories/http';
import { VisionImagePanel } from './components/VisionImagePanel';

export function AIPage({ sessions }: { sessions: ClassSession[] }) {
  const [config, setConfig] = useState<AIConfig>({
    sessionId: sessions[0]?.id ?? '',
    mode: 'simulation',
    sampleIntervalSeconds: 2,
    confidenceThreshold: 0.75,
    cameraIndex: 0,
    allowRemoteUpload: false,
    maxSamples: 5,
    maxDurationSeconds: 120,
  });
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    if (isDemo) return;
    let active = true;
    const load = async () => {
      try {
        const next = await request<AIStatus>('/admin/ai/status');
        if (active) {
          setStatus(next);
          setError('');
          if (next.stopReason === 'MAX_SAMPLES') setMessage('已达到采样次数上限，采集已停止。');
          else if (next.stopReason === 'TIME_LIMIT') setMessage('已达到实验时长上限，采集已停止。');
          else if (next.stopReason === 'ERROR') setMessage('');
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : 'AI 服务不可用');
      }
    };
    void load();
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, 3000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);
  const act = async (action: 'start' | 'stop') => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const next = await request<AIStatus>(`/admin/ai/${action}`, {
        method: 'POST',
        ...(action === 'start' ? { body: JSON.stringify(config) } : {}),
      });
      setStatus(next);
      setMessage(
        action === 'start'
          ? '采集任务已启动，请查看状态与实时看板。'
          : next.running
            ? '正在停止，当前推理结束后释放摄像头。'
            : '采集已停止，尚未发送的结果保留在重试队列。',
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '操作失败');
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <VisionImagePanel />
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>AI 推理服务集成</h2>
            <p>采样、过滤、上报与运行状态</p>
          </div>
          <span className="tag">{status?.running ? '采集中' : status ? '已停止' : '未连接'}</span>
        </div>
        <div className="ai-body">
          <div className="notice">
            摄像头实验支持 DeepSeek API 或本地 DeepFace。API
            模式仅需摄像头依赖，读取设备后释放，图像只在内存中处理；默认最多采样 5 次后停止。
          </div>
          {isDemo && (
            <p className="muted">
              当前为纯页面演示。运行 npm run dev:integration 后登录联调环境，即可操作独立 AI 服务。
            </p>
          )}
          <div className="ai-form">
            <label>
              关联课堂
              <select
                value={config.sessionId}
                onChange={(event) => setConfig({ ...config, sessionId: event.target.value })}
                disabled={status?.running}
              >
                {sessions.map((session) => (
                  <option key={session.id} value={session.id}>
                    {session.courseName} · {session.className}
                  </option>
                ))}
              </select>
            </label>
            <label>
              输入模式
              <select
                value={config.mode}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    mode: event.target.value as AIConfig['mode'],
                    allowRemoteUpload: false,
                    ...(event.target.value === 'camera-api' ? { sampleIntervalSeconds: 10 } : {}),
                  })
                }
                disabled={status?.running}
              >
                <option value="simulation">模拟输入（不使用摄像头）</option>
                <option value="camera-api">本机摄像头 + DeepSeek API</option>
                <option value="camera">真实摄像头 + DeepFace</option>
              </select>
            </label>
            <label>
              采样间隔（秒）
              <input
                type="number"
                min={config.mode === 'camera-api' ? 5 : 0.5}
                max="60"
                step="0.5"
                value={config.sampleIntervalSeconds}
                onChange={(event) =>
                  setConfig({ ...config, sampleIntervalSeconds: Number(event.target.value) })
                }
                disabled={status?.running}
              />
            </label>
            <label>
              {config.mode === 'camera-api'
                ? '自评分过滤阈值（0—1，未经校准）'
                : '置信度阈值（0—1）'}
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={config.confidenceThreshold}
                onChange={(event) =>
                  setConfig({ ...config, confidenceThreshold: Number(event.target.value) })
                }
                disabled={status?.running}
              />
            </label>
            {config.mode !== 'simulation' && (
              <label>
                摄像头编号
                <input
                  type="number"
                  min="0"
                  max="10"
                  value={config.cameraIndex}
                  onChange={(event) =>
                    setConfig({ ...config, cameraIndex: Number(event.target.value) })
                  }
                  disabled={status?.running}
                />
              </label>
            )}
            {config.mode === 'camera-api' && (
              <>
                <label>
                  最多采样次数
                  <input
                    type="number"
                    min="1"
                    max="60"
                    value={config.maxSamples}
                    disabled={status?.running}
                    onChange={(event) =>
                      setConfig({ ...config, maxSamples: Number(event.target.value) })
                    }
                  />
                </label>
                <label>
                  最长实验时长（秒）
                  <input
                    type="number"
                    min="10"
                    max="600"
                    value={config.maxDurationSeconds}
                    disabled={status?.running}
                    onChange={(event) =>
                      setConfig({ ...config, maxDurationSeconds: Number(event.target.value) })
                    }
                  />
                </label>
              </>
            )}
          </div>
          {config.mode === 'camera-api' && (
            <label className="vision-consent">
              <input
                type="checkbox"
                checked={config.allowRemoteUpload ?? false}
                disabled={status?.running}
                onChange={(event) =>
                  setConfig({ ...config, allowRemoteUpload: event.target.checked })
                }
              />
              将摄像头采样帧发送至 DeepSeek 进行表情分析；匿名结构化结果写入所选课堂。
            </label>
          )}
          {error && (
            <p className="login-error" role="alert">
              {error}
            </p>
          )}
          {status?.lastError && (
            <p className="login-error" role="alert">
              {status.lastError}
            </p>
          )}
          {message && (
            <p className="success-message" role="status">
              {message}
            </p>
          )}
          <div className="ai-actions">
            <button
              className="button"
              disabled={
                isDemo ||
                busy ||
                Boolean(status?.running) ||
                !config.sessionId ||
                config.sampleIntervalSeconds < 0.5 ||
                config.sampleIntervalSeconds > 60 ||
                config.confidenceThreshold < 0 ||
                config.confidenceThreshold > 1 ||
                (config.mode === 'camera-api' &&
                  (!config.allowRemoteUpload ||
                    config.sampleIntervalSeconds < 5 ||
                    !config.maxSamples ||
                    config.maxSamples > 60 ||
                    !config.maxDurationSeconds ||
                    config.maxDurationSeconds < 10 ||
                    config.maxDurationSeconds > 600))
              }
              onClick={() => void act('start')}
            >
              {busy ? '处理中…' : '启动采集'}
            </button>
            <button
              className="button secondary"
              disabled={isDemo || busy || !status?.running}
              onClick={() => void act('stop')}
            >
              停止采集
            </button>
          </div>
        </div>
      </section>
      <div className="metrics">
        {[
          ['采样次数', status?.sampled],
          ['成功上报', status?.submitted],
          ['低置信度 / 无效结果', status?.filtered],
          ['待重试结果', status?.pending],
        ].map(([title, value]) => (
          <div className="metric" key={String(title)}>
            <div className="metric-top">{title}</div>
            <strong>{value ?? '—'}</strong>
          </div>
        ))}
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>运行信息与数据保护</h2>
            <p>模型表情分数不能直接解释为课堂理解程度</p>
          </div>
        </div>
        <div className="ai-body">
          <dl className="status-grid">
            <dt>运行模式</dt>
            <dd>
              {status?.mode === 'camera-api'
                ? '本机摄像头 + DeepSeek API'
                : status?.mode === 'camera'
                  ? '真实摄像头'
                  : status?.mode === 'simulation'
                    ? '模拟输入'
                    : '尚未启动'}
            </dd>
            <dt>模型状态</dt>
            <dd>{status?.modelLoaded ? '已完成真实推理' : '未完成真实推理'}</dd>
            <dt>运行参数</dt>
            <dd>
              {status?.config
                ? `${status.config.sampleIntervalSeconds} 秒 / 阈值 ${status.config.confidenceThreshold}`
                : '尚无运行参数'}
            </dd>
            <dt>上次上报</dt>
            <dd>
              {status?.lastSubmittedAt
                ? new Date(status.lastSubmittedAt).toLocaleString('zh-CN')
                : '暂无'}
            </dd>
            <dt>失败次数</dt>
            <dd>{status?.failed ?? '—'}</dd>
            <dt>API 调用次数</dt>
            <dd>{status?.apiCalls ?? '—'}</dd>
            <dt>最近推理耗时</dt>
            <dd>
              {status?.lastInferenceMs != null
                ? `${(status.lastInferenceMs / 1000).toFixed(1)} 秒`
                : '暂无'}
            </dd>
            <dt>最近表情结果</dt>
            <dd>
              {status?.lastInferenceAt
                ? status.lastFaces.length
                  ? status.lastFaces
                      .map(
                        (face) =>
                          `${face.emotion ? emotions[face.emotion].label : '无法确定'} ${face.score.toFixed(2)}`,
                      )
                      .join('、')
                  : '未检出人脸'
                : '暂无'}
            </dd>
            <dt>停止原因</dt>
            <dd>
              {status?.stopReason
                ? {
                    REQUESTED: '手动停止',
                    MAX_SAMPLES: '达到采样次数上限',
                    TIME_LIMIT: '达到实验时长上限',
                    ERROR: '运行错误',
                  }[status.stopReason]
                : '—'}
            </dd>
          </dl>
          <p className="privacy-copy">
            默认不保存原始视频、人脸图像或人脸特征。仅在明确允许的 DeepSeek
            摄像头模式下发送采样帧；入库与重试队列只保存匿名结构化结果。API
            自评分未经校准，不能作为准确率或心理状态。
          </p>
          <p className="privacy-copy">
            开心、平静、低落、生气、惊讶、害怕、厌恶对应模型表情类别；“专注”和“困惑”保留为手动反馈选项，不从模型结果推断。
          </p>
        </div>
      </section>
    </>
  );
}
