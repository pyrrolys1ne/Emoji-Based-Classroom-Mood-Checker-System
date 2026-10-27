import { emotions, type EmojiRecord, type WorkspaceData } from '@mood/contracts';

export function distribution(records: EmojiRecord[]) {
  return Object.entries(emotions).map(([key, emotion]) => ({
    key,
    ...emotion,
    count: records.filter((record) => record.emotion === key).length,
  }));
}

export function sessionRecords(data: WorkspaceData, sessionId: string) {
  return data.records.filter((record) => !sessionId || record.sessionId === sessionId);
}

export function recordUserLabel(data: WorkspaceData, record: EmojiRecord) {
  if (!record.userId) return '匿名';
  return (
    data.users.find((user) => user.id === record.userId)?.username ??
    `用户 ${record.userId.slice(0, 8)}`
  );
}

export function csvCell(value: unknown) {
  const text = String(value ?? '');
  const safe = /^[\s]*[=+@-]|^[\t\r\n]/.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}

export function exportRecords(data: WorkspaceData, records: EmojiRecord[]) {
  const rows = [
    [
      '记录编号',
      '用户',
      '课程',
      '班级',
      '情绪',
      '来源',
      '模型分数',
      '记录时间',
      '模拟输入',
      '推理提供方',
      '分数类型',
    ],
    ...records.map((record) => {
      const session = data.sessions.find((item) => item.id === record.sessionId);
      return [
        record.id,
        recordUserLabel(data, record),
        session?.courseName ?? '',
        session?.className ?? '',
        emotions[record.emotion].label,
        record.source,
        record.confidence ?? '',
        record.recordedAt,
        record.simulated ? '是' : '否',
        record.inferenceProvider ?? '',
        record.confidenceKind ?? '',
      ];
    }),
  ];
  const blob = new Blob(['\uFEFF', rows.map((row) => row.map(csvCell).join(',')).join('\r\n')], {
    type: 'text/csv;charset=utf-8;',
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = '课堂情绪记录.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
