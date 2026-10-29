import type { AuthSession, ClassSession, Emotion, EmojiRecord, User } from '@mood/contracts';
import type { ReactNode } from 'react';

export type DataMode = 'demo' | 'api';
export type Page = 'feedback' | 'history' | 'teacher' | 'account';
export type AuthView = 'login' | 'register';
export interface LoginInput {
  username: string;
  password: string;
}
export interface RegisterInput extends LoginInput {
  email: string;
  role: 'STUDENT' | 'TEACHER';
}
export interface PasswordInput {
  oldPassword: string;
  newPassword: string;
}
export interface EmotionStatistics {
  total: number;
  distribution: Record<Emotion, number>;
}

export class ClientError extends Error {
  constructor(
    message: string,
    public readonly status = 0,
    public readonly code = 'CLIENT_ERROR',
  ) {
    super(message);
    this.name = 'ClientError';
  }
}

export interface ClientRepository {
  readonly mode: DataMode;
  login(input: LoginInput, signal?: AbortSignal): Promise<AuthSession>;
  register(input: RegisterInput, signal?: AbortSignal): Promise<void>;
  me(token: string, signal?: AbortSignal): Promise<User>;
  logout(token: string, signal?: AbortSignal): Promise<void>;
  changePassword(token: string, input: PasswordInput, signal?: AbortSignal): Promise<void>;
  sessions(token: string, signal?: AbortSignal): Promise<ClassSession[]>;
  submit(token: string, sessionId: string, emotion: Emotion, signal?: AbortSignal): Promise<void>;
  history(token: string, sessionId?: string, signal?: AbortSignal): Promise<EmojiRecord[]>;
  statistics(token: string, sessionId: string, signal?: AbortSignal): Promise<EmotionStatistics>;
}

export function canSubmitTo(session: ClassSession | null, now = Date.now()): boolean {
  return Boolean(
    session && Date.parse(session.startsAt) <= now && now < Date.parse(session.endsAt),
  );
}

export function messageOf(error: unknown): string {
  if (error instanceof ClientError) return error.message;
  if (error instanceof DOMException && error.name === 'AbortError') return '请求已取消，请重试。';
  return '暂时无法完成操作，请稍后重试。';
}

export function writeResultIsUnknown(error: unknown): boolean {
  if (!(error instanceof ClientError)) return true;
  if (error.status === 501) return false;
  return error.status === 0 || error.status >= 500 || (error.status >= 200 && error.status < 300);
}

export interface AuthViewProps {
  view: AuthView;
  onViewChange(view: AuthView): void;
  onLogin(input: LoginInput): Promise<boolean>;
  onRegister(input: RegisterInput): Promise<boolean>;
  pending: boolean;
  error: string;
  notice: string;
  mode: DataMode;
  initialUsername: string;
}
export interface AppShellProps {
  user: User;
  mode: DataMode;
  page: Page;
  onNavigate(page: Page): void;
  onLogout(): void;
  logoutPending: boolean;
  navigationPending?: boolean;
  notice: string;
  adminUrl: string;
  children: ReactNode;
}
export interface StudentViewProps {
  sessions: ClassSession[];
  selectedSessionId: string;
  onSessionChange(id: string): void;
  sessionsLoading: boolean;
  sessionsError: string;
  onSessionsRetry(): void;
  selectedEmotion: Emotion | null;
  onEmotionChange(emotion: Emotion): void;
  onSubmit(): void;
  submitting: boolean;
  submitError: string;
  submitNotice: string;
  canSubmit: boolean;
  records: EmojiRecord[];
  historyLoading: boolean;
  historyError: string;
  onHistoryRetry(): void;
}
export interface HistoryViewProps {
  sessions: ClassSession[];
  selectedSessionId: string;
  onSessionChange(id: string): void;
  records: EmojiRecord[];
  loading: boolean;
  error: string;
  onRetry(): void;
}
export interface TeacherViewProps extends HistoryViewProps {
  statistics: EmotionStatistics | null;
  statisticsLoading: boolean;
  statisticsError: string;
}
export interface AccountViewProps {
  user: User;
  onChangePassword(input: PasswordInput): Promise<boolean>;
  pending: boolean;
  error: string;
  notice: string;
}
