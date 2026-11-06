import {
  emotions,
  type EmojiRecord,
  type MultidimensionalStatistics,
  type SourceFilter,
  type WorkspaceData,
} from '@mood/contracts';

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
  const start = Math.floor(minimum / 60000) * 60000;
  const spanMinutes = Math.floor((maximum - start) / 60000) + 1;
  const step = Math.max(1, Math.ceil(spanMinutes / limit)) * 60000;
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

export function summarize(
  data: WorkspaceData,
  records: EmojiRecord[],
  source: SourceFilter,
): MultidimensionalStatistics {
  const distribution = Object.fromEntries(
    Object.keys(emotions).map((key) => [key, 0]),
  ) as MultidimensionalStatistics['distribution'];
  const groups = new Map<string, MultidimensionalStatistics['groups'][number]>();
  for (const record of records) {
    distribution[record.emotion]++;
    const classroom =
      record.classroom ?? data.sessions.find((item) => item.id === record.sessionId);
    if (!classroom) continue;
    const key = JSON.stringify([classroom.courseId, classroom.className]);
    const group = groups.get(key) ?? {
      courseId: classroom.courseId,
      courseName: classroom.courseName,
      className: classroom.className,
      total: 0,
      manual: 0,
      ai: 0,
    };
    group.total++;
    if (record.source === 'MANUAL') group.manual++;
    else group.ai++;
    groups.set(key, group);
  }
  return {
    total: records.length,
    distribution,
    source,
    groups: [...groups.values()],
    timeline: timeline(records).map((bucket) => ({
      startsAt: new Date(bucket.start).toISOString(),
      endsAt: new Date(bucket.end).toISOString(),
      total: bucket.count,
    })),
  };
}
