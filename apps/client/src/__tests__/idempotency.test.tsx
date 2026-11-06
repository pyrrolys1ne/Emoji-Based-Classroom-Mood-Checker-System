import { act, renderHook, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import {
  emotions,
  type EmotionStatistics,
  type AuthSession,
  type ClassSession,
} from '@mood/contracts';
import { ClientError, type ClientRepository } from '../models/client';
import { useClassroom } from '../viewmodels/useClassroom';

it('教师切换统计来源后忽略旧来源的迟到响应', async () => {
  const classroom: ClassSession = {
    id: 'classroom',
    courseId: 'course',
    courseName: '课程',
    teacherName: '教师',
    className: '班级',
    room: '101',
    startsAt: '2026-11-01T00:00:00Z',
    endsAt: '2026-11-01T01:00:00Z',
    scheduledUserIds: [],
  };
  const session: AuthSession = {
    token: 'teacher-token',
    user: {
      id: 'teacher',
      username: 'teacher',
      email: 'teacher@example.edu',
      role: 'TEACHER',
      status: 'ACTIVE',
    },
  };
  const distribution = (total: number) =>
    Object.fromEntries(
      Object.keys(emotions).map((key) => [key, key === 'HAPPY' ? total : 0]),
    ) as EmotionStatistics['distribution'];
  let resolveOld!: (value: EmotionStatistics) => void;
  const statistics = vi
    .fn<ClientRepository['statistics']>()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValue({ total: 1, distribution: distribution(1), source: 'AI' });
  const repository = {
    mode: 'api',
    sessions: vi.fn().mockResolvedValue([classroom]),
    history: vi.fn().mockResolvedValue([]),
    statistics,
  } as unknown as ClientRepository;
  const expire = vi.fn(() => false);
  const { result } = renderHook(() => useClassroom(repository, session, expire));
  await waitFor(() => expect(statistics).toHaveBeenCalledOnce());
  expect(statistics.mock.calls[0][3]).toBe('MANUAL');
  act(() => result.current.selectStatisticsSource('AI'));
  await waitFor(() => expect(result.current.statistics?.source).toBe('AI'));
  await act(async () =>
    resolveOld({ total: 99, distribution: distribution(99), source: 'MANUAL' }),
  );
  expect(result.current.statistics?.total).toBe(1);
  expect(statistics.mock.calls.at(-1)?.[3]).toBe('AI');
});

it('reuses the key after an unknown write and allocates a new key after success', async () => {
  const session: AuthSession = {
    token: 'synthetic-token',
    user: {
      id: 'student',
      username: 'student',
      email: 'student@example.edu',
      role: 'STUDENT',
      status: 'ACTIVE',
    },
  };
  const classroom: ClassSession = {
    id: 'classroom',
    courseId: 'course',
    courseName: '数据库',
    teacherName: '测试教师',
    className: '测试班',
    room: '101',
    startsAt: new Date(Date.now() - 60000).toISOString(),
    endsAt: new Date(Date.now() + 3600000).toISOString(),
    scheduledUserIds: ['student'],
  };
  const submit = vi
    .fn<ClientRepository['submit']>()
    .mockRejectedValueOnce(new ClientError('服务暂时不可用', 503))
    .mockResolvedValue(undefined);
  const repository = {
    mode: 'api',
    sessions: async () => [classroom],
    history: async () => [],
    submit,
  } as unknown as ClientRepository;
  const expire = () => false;
  const { result } = renderHook(() => useClassroom(repository, session, expire));
  await waitFor(() => expect(result.current.canSubmit).toBe(true));
  act(() => result.current.selectEmotion('HAPPY'));
  await act(() => result.current.submit());
  expect(result.current.submitError).toContain('核实');
  expect(submit).toHaveBeenCalledTimes(1);
  await act(() => result.current.submit());
  expect(submit.mock.calls[1][4]).toBe(submit.mock.calls[0][4]);
  expect(result.current.submitNotice).toContain('已保存');
  act(() => result.current.selectEmotion('HAPPY'));
  await act(() => result.current.submit());
  expect(submit.mock.calls[2][4]).not.toBe(submit.mock.calls[0][4]);
});
