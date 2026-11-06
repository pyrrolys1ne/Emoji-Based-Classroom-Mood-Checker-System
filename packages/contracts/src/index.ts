export const emotions = {
  HAPPY: { emoji: '😊', label: '开心', color: '#3b9c7a' },
  FOCUSED: { emoji: '🤓', label: '专注', color: '#4c7ecf' },
  NEUTRAL: { emoji: '😐', label: '平静', color: '#a79457' },
  CONFUSED: { emoji: '🤔', label: '困惑', color: '#d58a44' },
  SAD: { emoji: '😔', label: '低落', color: '#9b83bb' },
  ANGRY: { emoji: '😠', label: '生气', color: '#c96464' },
  SURPRISED: { emoji: '😮', label: '惊讶', color: '#c79736' },
  FEAR: { emoji: '😨', label: '害怕', color: '#658aac' },
  DISGUST: { emoji: '😣', label: '厌恶', color: '#8d9960' },
} as const;

export type Emotion = keyof typeof emotions;
export type AIEmotion = Exclude<Emotion, 'FOCUSED' | 'CONFUSED'>;
export type Role = 'STUDENT' | 'TEACHER' | 'ADMIN';
export type RecordSource = 'MANUAL' | 'AI';
export type SourceFilter = RecordSource | 'ALL';
export type TeacherApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED';
export type UserStatus = 'ACTIVE' | 'DISABLED';
export interface User {
  id: string;
  username: string;
  email: string;
  role: Role;
  status: UserStatus;
  studentNo?: string | null;
  realName?: string | null;
  className?: string | null;
  teacherApprovalStatus?: TeacherApprovalStatus | null;
}
export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  role: 'STUDENT' | 'TEACHER';
  studentNo?: string | null;
  realName?: string | null;
  className?: string | null;
}
export interface StudentProfileRequest {
  studentNo?: string | null;
  realName?: string | null;
  className?: string | null;
}
export interface TeacherReviewRequest {
  decision: 'APPROVED' | 'REJECTED';
  reason?: string | null;
}
export interface CourseRequest {
  name: string;
  teacherId: string;
}
export interface Course extends CourseRequest {
  id: string;
}
export interface TeacherApplication {
  id: string;
  userId: string;
  status: TeacherApprovalStatus;
  submittedAt: string;
  reviewedAt: string | null;
  reviewedBy: string | null;
  reason: string | null;
}
export interface SessionRequest {
  courseId: string;
  teacherId?: string;
  startsAt: string;
  endsAt: string;
  room: string;
  className: string;
}
export interface RecordFilters {
  sessionId?: string;
  userId?: string;
  course?: string;
  class?: string;
  from?: string;
  to?: string;
  source?: SourceFilter;
  emotion?: Emotion;
}
export interface EmotionStatistics {
  total: number;
  distribution: Record<Emotion, number>;
  source?: SourceFilter;
}
export interface StatisticsBucket {
  startsAt: string;
  endsAt: string;
  total: number;
}
export interface StatisticsGroup {
  courseId: string;
  courseName: string;
  className: string;
  total: number;
  manual: number;
  ai: number;
}
export interface MultidimensionalStatistics extends EmotionStatistics {
  timeline: StatisticsBucket[];
  groups: StatisticsGroup[];
}
export interface ExportFilters extends RecordFilters {
  format?: 'csv';
}
export interface ClassroomSummary {
  id: string;
  courseId: string;
  courseName: string;
  teacherName: string;
  teacherId?: string;
  className: string;
  room: string;
  startsAt: string;
  endsAt: string;
}
export interface ClassSession extends ClassroomSummary {
  scheduledUserIds: string[];
  scheduledStudents?: ClassroomStudent[];
}
export interface ClassroomStudent {
  id: string;
  username: string;
  studentNo: string | null;
  realName: string | null;
  className: string | null;
  status: UserStatus;
}
export interface EmojiRecord {
  id: string;
  userId: string | null;
  sessionId: string;
  emotion: Emotion;
  source: RecordSource;
  confidence: number | null;
  recordedAt: string;
  simulated?: boolean;
  inferenceProvider?: 'DeepSeek' | 'DeepFace' | null;
  confidenceKind?: 'self_reported' | 'model_score' | null;
  classroom?: ClassroomSummary | null;
  student?: ClassroomStudent | null;
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
export interface AIResultRequest {
  sessionId: string;
  emotion: AIEmotion;
  confidence: number;
  recordedAt: string;
  deviceId: string;
  source?: 'AI';
  simulated?: boolean;
  inferenceProvider?: 'DeepSeek' | 'DeepFace' | null;
  confidenceKind?: 'self_reported' | 'model_score' | null;
}
export type AIIngestResult =
  | { accepted: true; created: boolean; record: EmojiRecord }
  | { accepted: false; reason: 'LOW_CONFIDENCE' };

export interface AuthSession {
  token: string;
  user: User;
}
export interface WsTicketResponse {
  ticket: string;
  expiresAt: string;
}
export interface RealtimeSnapshot {
  type: 'snapshot';
  total: number;
  latestId: string | null;
  version?: string;
}
export interface RealtimeDashboard {
  records: EmojiRecord[];
  total: number;
  latestId: string | null;
  updatedAt: string;
}
export interface AIConfig {
  sessionId: string;
  mode: 'simulation' | 'camera' | 'camera-api';
  sampleIntervalSeconds: number;
  confidenceThreshold: number;
  cameraIndex: number;
  allowRemoteUpload?: boolean;
  maxSamples?: number;
  maxDurationSeconds?: number;
}
export interface AIStatus {
  running: boolean;
  mode: 'simulation' | 'camera' | 'camera-api' | null;
  modelLoaded: boolean;
  sessionId: string | null;
  sampled: number;
  submitted: number;
  filtered: number;
  failed: number;
  pending: number;
  lastError: string | null;
  lastSubmittedAt: string | null;
  config: AIConfig | null;
  apiCalls: number;
  lastInferenceMs: number | null;
  lastInferenceAt: string | null;
  lastFaces: { emotion: AIEmotion | null; score: number }[];
  stopReason: 'REQUESTED' | 'MAX_SAMPLES' | 'TIME_LIMIT' | 'ERROR' | null;
}

export interface VisionSample {
  id: string;
  title: string;
  sourceUrl: string | null;
  credit: string;
  license: string;
  kind: 'portrait' | 'negative-control';
  available: boolean;
}
export interface VisionStatus {
  provider: 'DeepSeek';
  model: string;
  configured: boolean;
  confidenceKind: 'self_reported';
  calibrated: false;
  samples: VisionSample[];
}
export interface VisionResult {
  imageId: string;
  provider: 'DeepSeek';
  model: string;
  confidenceKind: 'self_reported';
  calibrated: false;
  sampleOnly: true;
  persisted: false;
  elapsedMs: number;
  faces: { label: string; score: number; emotion: AIEmotion | null }[];
}
