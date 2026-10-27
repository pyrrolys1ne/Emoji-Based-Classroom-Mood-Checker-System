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
  simulated?: boolean;
  inferenceProvider?: 'DeepSeek' | 'DeepFace' | null;
  confidenceKind?: 'self_reported' | 'model_score' | null;
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

export interface AuthSession {
  token: string;
  user: User;
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
  lastFaces: { emotion: Emotion | null; score: number }[];
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
  faces: { label: string; score: number; emotion: Emotion | null }[];
}
