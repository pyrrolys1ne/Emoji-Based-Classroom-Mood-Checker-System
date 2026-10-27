import { useEffect, useState } from 'react';
import { emotions, type VisionResult, type VisionStatus } from '@mood/contracts';
import { isDemo, request } from '../../repositories/http';

export function VisionImagePanel() {
  const [status, setStatus] = useState<VisionStatus | null>(null);
  const [imageId, setImageId] = useState('');
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<VisionResult | null>(null);
  useEffect(() => {
    if (isDemo) return;
    const controller = new AbortController();
    void request<VisionStatus>('/admin/ai/vision', { signal: controller.signal })
      .then((next) => {
        if (controller.signal.aborted) return;
        setStatus(next);
        setImageId(next.samples.find((sample) => sample.available)?.id ?? '');
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : '识图服务不可用');
      });
    return () => controller.abort();
  }, []);
  const sample = status?.samples.find((item) => item.id === imageId);
  const analyze = async () => {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const next = await request<VisionResult>(
        '/admin/ai/analyze-image',
        { method: 'POST', body: JSON.stringify({ imageId, allowRemoteUpload: consent }) },
        45000,
      );
      setResult(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '识图请求失败');
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>图片表情分析</h2>
          <p>DeepSeek · {status?.model ?? 'deepseek-flash'} · 无需安装本地模型</p>
        </div>
        <span className="tag">{status?.configured ? 'API 已配置' : 'API 未配置'}</span>
      </div>
      <div className="ai-body">
        <p className="privacy-copy">
          使用公开人像与无人脸对照图测试识图。图片会发送至
          DeepSeek；结果仅供本次查看，不计入课堂统计。
        </p>
        {isDemo && <p className="muted">请在联调环境中使用图片分析。</p>}
        <div className="ai-form">
          <label>
            公开测试样本
            <select
              value={imageId}
              disabled={busy || !status}
              onChange={(event) => {
                setImageId(event.target.value);
                setResult(null);
                setConsent(false);
                setError('');
              }}
            >
              {!imageId && <option value="">暂无已下载样本</option>}
              {status?.samples.map((item) => (
                <option key={item.id} value={item.id} disabled={!item.available}>
                  {item.title}
                  {item.available ? '' : '（未下载）'}
                </option>
              ))}
            </select>
          </label>
          <div className="sample-credit">
            <span>{sample?.credit ?? '请选择样本'}</span>
            <small>{sample?.license}</small>
            {sample?.sourceUrl && (
              <a href={sample.sourceUrl} target="_blank" rel="noreferrer">
                查看图片与来源
              </a>
            )}
          </div>
        </div>
        <label className="vision-consent">
          <input
            type="checkbox"
            checked={consent}
            disabled={busy || !sample?.available}
            onChange={(event) => setConsent(event.target.checked)}
          />
          将所选公开样本发送至 DeepSeek 分析
        </label>
        {error && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}
        <div className="ai-actions">
          <button
            className="button"
            disabled={isDemo || busy || !consent || !sample?.available || !status?.configured}
            onClick={() => void analyze()}
          >
            {busy ? '正在分析…' : '分析图片'}
          </button>
        </div>
        {result && (
          <div className="vision-result" role="status">
            <p>
              {result.faces.length ? `检出 ${result.faces.length} 张人脸` : '未检出人脸'} · 耗时{' '}
              {(result.elapsedMs / 1000).toFixed(1)} 秒
            </p>
            {result.faces.map((face, index) => {
              const expression = face.emotion ? emotions[face.emotion] : null;
              return (
                <p key={index}>
                  人脸 {index + 1}：
                  {expression ? `${expression.emoji} ${expression.label}` : '无法确定'}
                  {' · '}模型自评分 {face.score.toFixed(2)}
                </p>
              );
            })}
            <small>
              自评分未经校准，不代表准确率或心理状态。公开样本无表情真值标注，不能据此评估模型准确率。
            </small>
          </div>
        )}
      </div>
    </section>
  );
}
