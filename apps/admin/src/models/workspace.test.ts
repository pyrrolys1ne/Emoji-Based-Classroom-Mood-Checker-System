import { describe, expect, it } from 'vitest';
import type { EmojiRecord } from '@mood/contracts';
import { csvCell } from './workspace';
import { timeline } from './statistics';

const row = (at: string): EmojiRecord => ({
  id: at,
  userId: null,
  sessionId: 's',
  emotion: 'HAPPY',
  source: 'AI',
  confidence: 0.9,
  recordedAt: at,
});

describe('实际课堂时间趋势', () => {
  it('不同小时的同一分钟不会合并，且保留时间顺序', () => {
    const buckets = timeline([row('2026-10-27T10:05:00+08:00'), row('2026-10-27T09:05:00+08:00')]);
    const populated = buckets.filter((bucket) => bucket.count);
    expect(populated).toHaveLength(2);
    expect(populated[0].start).toBeLessThan(populated[1].start);
    expect(buckets.reduce((sum, bucket) => sum + bucket.count, 0)).toBe(2);
  });
  it('跨天也不丢记录，空数据不生成虚构趋势', () => {
    expect(timeline([])).toEqual([]);
    const buckets = timeline([row('2026-10-26T23:59:00+08:00'), row('2026-10-27T00:01:00+08:00')]);
    expect(buckets.reduce((sum, bucket) => sum + bucket.count, 0)).toBe(2);
    expect(buckets[0].end).toBeLessThanOrEqual(buckets.at(-1)!.end);
  });
});

describe('CSV 注入防护', () => {
  it.each([
    '=HYPERLINK("https://example.invalid")',
    '+SUM(1,2)',
    '-1+2',
    '@SUM(A1)',
    ' \t=1',
    '\tcmd',
  ])('阻止公式输入 %s', (value) => {
    expect(csvCell(value).startsWith('"\'')).toBe(true);
  });
  it('正确转义逗号、引号和换行', () => {
    expect(csvCell('姓名,"备注"\n第二行')).toBe('"姓名,""备注""\n第二行"');
  });
});
