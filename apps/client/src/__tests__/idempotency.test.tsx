import { act, renderHook, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { type AuthSession, type ClassSession } from '@mood/contracts';
import { ClientError, type ClientRepository } from '../models/client';
import { useClassroom } from '../viewmodels/useClassroom';

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
