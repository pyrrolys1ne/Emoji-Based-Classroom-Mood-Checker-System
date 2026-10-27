import { useId } from 'react';
import type { EmojiRecord } from '@mood/contracts';
import { distribution } from '../../models/workspace';
import { timeline } from '../../models/statistics';

export function EmotionChart({ records }: { records: EmojiRecord[] }) {
  return (
    <div className="emotion-chart">
      {distribution(records).map((item) => (
        <div className="emotion-row" key={item.key}>
          <span className="emotion-name">
            {item.emoji} {item.label}
          </span>
          <div className="bar-track">
            <span
              style={{
                width: `${records.length ? (item.count / records.length) * 100 : 0}%`,
                background: item.color,
              }}
            />
          </div>
          <strong>{item.count}</strong>
          <span className="muted">
            {records.length ? Math.round((item.count / records.length) * 100) : 0}%
          </span>
        </div>
      ))}
    </div>
  );
}

export function Trend({ records }: { records: EmojiRecord[] }) {
  const buckets = timeline(records);
  const id = useId().replaceAll(':', '');
  if (!buckets.length) return <div className="empty">当前范围暂无情绪趋势数据</div>;
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
  const x = (index: number) =>
    buckets.length === 1 ? 270 : 40 + (index / (buckets.length - 1)) * 460;
  const y = (count: number) => 145 - (count / max) * 108;
  const points = buckets.map((bucket, index) => `${x(index)},${y(bucket.count)}`).join(' ');
  return (
    <div className="trend">
      <svg viewBox="0 0 540 190" role="img" aria-label="按实际日期时间顺序统计的课堂反馈趋势">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b9c7a" stopOpacity=".22" />
            <stop offset="100%" stopColor="#3b9c7a" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2].map((index) => (
          <line
            key={index}
            x1="40"
            x2="500"
            y1={37 + index * 54}
            y2={37 + index * 54}
            stroke="#e8eeeb"
            strokeDasharray="4 5"
          />
        ))}
        <polygon
          points={`${x(0)},150 ${points} ${x(buckets.length - 1)},150`}
          fill={`url(#${id})`}
        />
        <polyline points={points} fill="none" stroke="#329374" strokeWidth="3" />
        {buckets.map((bucket, index) => (
          <g key={bucket.start}>
            <circle cx={x(index)} cy={y(bucket.count)} r="4" fill="#329374">
              <title>
                {bucket.label}：{bucket.count} 条
              </title>
            </circle>
            {(index === 0 ||
              index === buckets.length - 1 ||
              index === Math.floor(buckets.length / 2)) && (
              <text
                x={x(index)}
                y="179"
                textAnchor={index === 0 ? 'start' : index === buckets.length - 1 ? 'end' : 'middle'}
              >
                {bucket.label}
              </text>
            )}
          </g>
        ))}
      </svg>
      <p className="chart-note">
        按实际时间顺序聚合 · 每段 {Math.round((buckets[0].end - buckets[0].start) / 60000)} 分钟 ·{' '}
        {records.length} 条记录
      </p>
    </div>
  );
}
