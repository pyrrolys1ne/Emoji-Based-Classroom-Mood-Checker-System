import {
  emotions,
  type ExportFilters,
  type MultidimensionalStatistics,
  type RecordFilters,
} from '@mood/contracts';
import { request, requestCsv } from './http';

export function statisticsQuery(filters: RecordFilters): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters))
    if (value !== undefined && value !== '') query.set(key, value);
  return query.toString();
}

export function validStatistics(value: unknown): value is MultidimensionalStatistics {
  if (!value || typeof value !== 'object') return false;
  const data = value as MultidimensionalStatistics;
  const count = (x: unknown): x is number =>
    typeof x === 'number' && Number.isSafeInteger(x) && x >= 0;
  const time = (x: unknown) =>
    typeof x === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(x) && Number.isFinite(Date.parse(x));
  return (
    count(data.total) &&
    ['MANUAL', 'AI', 'ALL'].includes(data.source ?? '') &&
    !!data.distribution &&
    Object.keys(emotions).every((key) => count(data.distribution[key as keyof typeof emotions])) &&
    Object.keys(data.distribution).length === Object.keys(emotions).length &&
    Object.values(data.distribution).reduce((sum, n) => sum + n, 0) === data.total &&
    Array.isArray(data.timeline) &&
    data.timeline.every(
      (bucket, index, rows) =>
        !!bucket &&
        time(bucket.startsAt) &&
        time(bucket.endsAt) &&
        Date.parse(bucket.startsAt) < Date.parse(bucket.endsAt) &&
        count(bucket.total) &&
        (index === 0 || Date.parse(rows[index - 1].endsAt) === Date.parse(bucket.startsAt)),
    ) &&
    data.timeline.reduce((sum, bucket) => sum + bucket.total, 0) === data.total &&
    Array.isArray(data.groups) &&
    data.groups.every(
      (group) =>
        !!group &&
        ['courseId', 'courseName', 'className'].every(
          (key) =>
            typeof group[key as keyof typeof group] === 'string' &&
            String(group[key as keyof typeof group]).length > 0,
        ) &&
        count(group.total) &&
        count(group.manual) &&
        count(group.ai) &&
        group.manual + group.ai === group.total,
    ) &&
    data.groups.reduce((sum, group) => sum + group.total, 0) === data.total
  );
}

export const statisticsRepository = {
  async statistics(
    filters: RecordFilters,
    signal?: AbortSignal,
  ): Promise<MultidimensionalStatistics> {
    const data = await request<unknown>(`/admin/statistics?${statisticsQuery(filters)}`, {
      signal,
    });
    if (!validStatistics(data) || data.source !== (filters.source ?? 'MANUAL'))
      throw new Error('服务返回的统计格式或来源无效。');
    return data;
  },
  exportCsv(filters: ExportFilters, signal?: AbortSignal): Promise<Blob> {
    const { format: _format, ...scope } = filters;
    return requestCsv(
      `/admin/emoji/export?${statisticsQuery({ ...scope, source: filters.source ?? 'MANUAL' })}&format=csv`,
      signal,
    );
  },
};
