export const emotions = {
  HAPPY: { emoji: '😊', label: '开心', color: '#3b9c7a' },
  FOCUSED: { emoji: '🤓', label: '专注', color: '#4c7ecf' },
  NEUTRAL: { emoji: '😐', label: '平静', color: '#a79457' },
  CONFUSED: { emoji: '🤔', label: '困惑', color: '#d58a44' },
  SAD: { emoji: '😔', label: '低落', color: '#9b83bb' },
} as const;

export type Emotion = keyof typeof emotions;
export type Role = 'STUDENT' | 'TEACHER' | 'ADMIN';
export type RecordSource = 'MANUAL' | 'AI';
export interface User {
  id: string;
  username: string;
  email: string;
  role: Role;
  status: 'ACTIVE' | 'DISABLED';
}
export interface ClassSession {
  id: string;
  courseId: string;
  courseName: string;
  teacherName: string;
  className: string;
  room: string;
  startsAt: string;
  endsAt: string;
  scheduledUserIds: string[];
}
export interface EmojiRecord {
  id: string;
  userId: string | null;
  sessionId: string;
  emotion: Emotion;
  source: RecordSource;
  confidence: number | null;
  recordedAt: string;
}
export interface WorkspaceData {
  users: User[];
  sessions: ClassSession[];
  records: EmojiRecord[];
}
export interface ApiResponse<T> {
  code: string;
  message: string;
  data: T;
}
export interface EmojiSubmission {
  sessionId: string;
  emotion: Emotion;
}
