import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { emotions, type ClassSession, type EmojiRecord, type User } from '@mood/contracts';
import type { StudentViewProps, TeacherViewProps } from '../models/client';
import { AccountView, AuthView, StudentView, TeacherView } from '../views';

afterEach(cleanup);
const session: ClassSession = {
  id: 'session-1',
  courseId: 'course-1',
  courseName: '物理',
  teacherName: '教师',
  className: '一班',
  room: '教室',
  startsAt: '2026-01-01T00:00:00Z',
  endsAt: '2026-01-01T02:00:00Z',
  scheduledUserIds: ['student-12345678'],
};
const user: User = {
  id: 'student-12345678',
  username: 'student',
  email: 'student@example.test',
  role: 'STUDENT',
  status: 'ACTIVE',
};
const record = (
  id: string,
  userId: string | null,
  source: 'MANUAL' | 'AI',
  emotion: 'HAPPY' | 'SAD',
): EmojiRecord => ({
  id,
  userId,
  source,
  emotion,
  sessionId: session.id,
  confidence: null,
  recordedAt: '2026-01-01T01:00:00Z',
});
const studentProps = (): StudentViewProps => ({
  sessions: [session],
  selectedSessionId: session.id,
  onSessionChange: vi.fn(),
  sessionsLoading: false,
  sessionsError: '',
  onSessionsRetry: vi.fn(),
  selectedEmotion: 'HAPPY',
  onEmotionChange: vi.fn(),
  onSubmit: vi.fn(),
  submitting: false,
  submitError: '',
  submitNotice: '',
  canSubmit: true,
  records: [],
  historyLoading: false,
  historyError: '',
  onHistoryRetry: vi.fn(),
});

describe('客户端视图', () => {
  it('注册密码不一致时显示错误且不发出注册请求', async () => {
    const submit = vi.fn().mockResolvedValue(true);
    const u = userEvent.setup();
    render(
      <AuthView
        view="register"
        onViewChange={vi.fn()}
        onLogin={vi.fn()}
        onRegister={submit}
        pending={false}
        error=""
        notice=""
        mode="demo"
        initialUsername=""
      />,
    );
    await u.type(screen.getByLabelText('用户名'), 'student');
    await u.type(screen.getByLabelText('邮箱'), 'student@example.test');
    await u.type(screen.getByLabelText('密码', { exact: true }), 'password1');
    await u.type(screen.getByLabelText('确认密码'), 'password2');
    await u.click(screen.getByRole('button', { name: '注册' }));
    expect(screen.getByRole('alert')).toHaveTextContent('两次输入的密码不一致');
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByLabelText('申请身份')).not.toHaveTextContent('管理员');
  });
  it('改密确认不一致时不提交，失败时保留输入', async () => {
    const change = vi.fn().mockResolvedValue(false);
    const u = userEvent.setup();
    render(
      <AccountView user={user} onChangePassword={change} pending={false} error="" notice="" />,
    );
    await u.type(screen.getByLabelText('当前密码'), 'oldpassword');
    await u.type(screen.getByLabelText('新密码', { exact: true }), 'newpassword');
    await u.type(screen.getByLabelText('确认新密码'), 'different');
    await u.click(screen.getByRole('button', { name: '修改密码' }));
    expect(change).not.toHaveBeenCalled();
    await u.clear(screen.getByLabelText('确认新密码'));
    await u.type(screen.getByLabelText('确认新密码'), 'newpassword');
    await u.click(screen.getByRole('button', { name: '修改密码' }));
    expect(change).toHaveBeenCalledWith({ oldPassword: 'oldpassword', newPassword: 'newpassword' });
    expect(screen.getByLabelText('新密码', { exact: true })).toHaveValue('newpassword');
  });
  it('提交期间禁用操作，失败保留选择，错误可重试', async () => {
    const props = studentProps();
    const u = userEvent.setup();
    const { rerender } = render(<StudentView {...props} submitting />);
    expect(screen.getByRole('button', { name: '正在提交…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '开心' })).toBeDisabled();
    rerender(<StudentView {...props} submitError="提交失败" historyError="加载失败" />);
    expect(screen.getByRole('button', { name: '开心' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('提交失败')).toBeVisible();
    await u.click(screen.getByRole('button', { name: '重试' }));
    expect(props.onHistoryRetry).toHaveBeenCalledOnce();
  });
  it('教师课堂加载失败时提供重试，而非显示空课堂', async () => {
    const retry = vi.fn();
    const u = userEvent.setup();
    render(
      <TeacherView
        sessions={[]}
        selectedSessionId=""
        onSessionChange={vi.fn()}
        records={[]}
        loading={false}
        error="课堂加载失败"
        onRetry={retry}
        statistics={null}
        statisticsLoading={false}
        statisticsError=""
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('课堂加载失败');
    expect(screen.queryByText('暂无可查看的课堂。')).not.toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: '重试' }));
    expect(retry).toHaveBeenCalledOnce();
  });
  it('教师筛选学生和匿名 AI 时，课堂整体分布不受筛选影响', async () => {
    const distribution = Object.fromEntries(
      Object.keys(emotions).map((k) => [k, k === 'HAPPY' ? 2 : k === 'SAD' ? 1 : 0]),
    ) as NonNullable<TeacherViewProps['statistics']>['distribution'];
    const props: TeacherViewProps = {
      sessions: [session],
      selectedSessionId: session.id,
      onSessionChange: vi.fn(),
      records: [
        record('r1', 'student-12345678', 'MANUAL', 'HAPPY'),
        record('r2', 'other-12345678', 'MANUAL', 'SAD'),
        record('r3', 'private-ai-identity', 'AI', 'HAPPY'),
      ],
      loading: false,
      error: '',
      onRetry: vi.fn(),
      statistics: { total: 3, distribution },
      statisticsLoading: false,
      statisticsError: '',
    };
    const u = userEvent.setup();
    render(<TeacherView {...props} />);
    const stats = screen.getByRole('heading', { name: '课堂整体分布' }).closest('section')!;
    const history = screen.getByRole('heading', { name: '课堂历史' }).closest('section')!;
    await u.selectOptions(screen.getByLabelText('筛选记录'), 'student-12345678');
    expect(within(stats).getByText('共 3 条记录')).toBeVisible();
    expect(within(history).getAllByRole('listitem')).toHaveLength(1);
    expect(within(history).queryByText('AI 匿名', { selector: 'span' })).not.toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText('筛选记录'), 'ai');
    expect(within(history).getAllByRole('listitem')).toHaveLength(1);
    expect(within(history).getByText('AI 匿名', { selector: 'span' })).toBeVisible();
    expect(history).not.toHaveTextContent('private-');
    expect(screen.getByLabelText('筛选记录')).not.toHaveTextContent('private-');
    expect(within(stats).getByText('共 3 条记录')).toBeVisible();
  });
});
