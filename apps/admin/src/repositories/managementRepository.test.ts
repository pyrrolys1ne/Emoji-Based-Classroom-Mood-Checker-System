import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const request = vi.hoisted(() => vi.fn());
vi.mock('./http', () => ({ isDemo: false, isIntegration: false, request }));
import { managementRepository as repo } from './managementRepository';
beforeEach(() => {
  request.mockReset();
});
afterEach(() => vi.unstubAllGlobals());
it('preserves nullable student fields and escapes the path identifier', async () => {
  request.mockResolvedValue({ id: 's/a', role: 'STUDENT', username: 'student' });
  await repo.saveStudent('s/a', { studentNo: null, realName: '姓名' });
  expect(request).toHaveBeenCalledWith('/admin/users/s%2Fa/student-profile', {
    method: 'PUT',
    body: '{"studentNo":null,"realName":"姓名"}',
  });
});
it('uses POST for creation and PUT for course editing', async () => {
  request.mockResolvedValue({ id: 'c', name: '课程', teacherId: 't' });
  await repo.saveCourse({ name: '课程', teacherId: 't' });
  expect(request.mock.calls[0][0]).toBe('/admin/courses');
  expect(request.mock.calls[0][1].method).toBe('POST');
  await repo.saveCourse({ name: '课程', teacherId: 't' }, 'c');
  expect(request.mock.calls[1][0]).toBe('/admin/courses/c');
  expect(request.mock.calls[1][1].method).toBe('PUT');
});
it('forwards session timezone timestamps and omits an unspecified teacher', async () => {
  request.mockResolvedValue({ id: 's', courseId: 'c', scheduledUserIds: [] });
  const body = {
    courseId: 'c',
    startsAt: '2030-01-01T09:00:00+08:00',
    endsAt: '2030-01-01T10:00:00+08:00',
    room: 'R',
    className: '班',
  };
  await repo.saveSession(body);
  expect(JSON.parse(request.mock.calls[0][1].body)).toEqual(body);
  expect(request.mock.calls[0][1].method).toBe('POST');
  await repo.saveSession(body, 's');
  expect(request.mock.calls[1][0]).toBe('/admin/sessions/s');
  expect(request.mock.calls[1][1].method).toBe('PUT');
});
it.each([
  null,
  { id: 'a', userId: 'u', status: 'PENDING' },
  { id: 'wrong', userId: 'u', status: 'APPROVED' },
])('rejects an invalid approval receipt %j', async (value) => {
  request.mockResolvedValue(value);
  await expect(repo.review('a', { decision: 'APPROVED' })).rejects.toThrow('核对结果');
});
it('does not retry or hide a rejected write', async () => {
  request.mockRejectedValue(new Error('学号已存在'));
  const error = await repo
    .saveStudent('s', { studentNo: 'duplicate' })
    .catch((reason: Error) => reason);
  expect(error).toHaveProperty('message', '学号已存在');
  expect(request.mock.calls).toHaveLength(1);
});
it('accepts reviewed applications and rejects malformed list responses', async () => {
  request.mockResolvedValue([{ id: 'a', userId: 'u', status: 'REJECTED' }]);
  expect(await repo.applications()).toHaveLength(1);
  request.mockResolvedValue([{ id: 'a', userId: 'u', status: 'unknown' }]);
  await expect(repo.applications()).rejects.toThrow('回执');
  request.mockResolvedValue({ items: [] });
  await expect(repo.courses()).rejects.toThrow('回执');
});
