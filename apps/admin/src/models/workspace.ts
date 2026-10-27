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

export function csvCell(value: unknown) {
  const text = String(value ?? '');
  const safe = /^[\s]*[=+@-]|^[\t\r\n]/.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}

export function exportRecords(data: WorkspaceData, records: EmojiRecord[]) {
  const rows = [
    ['记录编号', '用户', '课程', '班级', '情绪', '来源', '置信度', '记录时间'],
    ...records.map((record) => {
      const session = data.sessions.find((item) => item.id === record.sessionId);
      return [
        record.id,
        data.users.find((user) => user.id === record.userId)?.username ?? '匿名',
        session?.courseName ?? '',
        session?.className ?? '',
        emotions[record.emotion].label,
        record.source,
        record.confidence ?? '',
        record.recordedAt,
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
