import type { EmojiRecord } from '@mood/contracts';

export interface TimeBucket {
  start: number;
  end: number;
  count: number;
  label: string;
}

export function timeline(records: EmojiRecord[], limit = 12): TimeBucket[] {
  const times = records.map((record) => Date.parse(record.recordedAt)).filter(Number.isFinite);
  if (!times.length) return [];
  const minimum = Math.min(...times);
  const maximum = Math.max(...times);
  const step = Math.max(60000, Math.ceil((maximum - minimum + 1) / limit / 60000) * 60000);
  const start = Math.floor(minimum / step) * step;
  const count = Math.floor((maximum - start) / step) + 1;
  return Array.from({ length: count }, (_, index) => {
    const bucketStart = start + index * step;
    return {
      start: bucketStart,
      end: bucketStart + step,
      count: times.filter((time) => time >= bucketStart && time < bucketStart + step).length,
      label: new Date(bucketStart).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      }),
    };
  });
}
