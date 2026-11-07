// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { User, WorkspaceData } from '@mood/contracts';
const mocks = vi.hoisted(() => ({
  courses: vi.fn(),
  applications: vi.fn(),
  saveCourse: vi.fn(),
  saveSession: vi.fn(),
  review: vi.fn(),
  saveStudent: vi.fn(),
}));
vi.mock('../repositories/managementRepository', () => ({
  canManage: true,
  managementNotice: '正式 API 模式',
  managementRepository: mocks,
}));
import { AcademicPage } from './AcademicPage';
import { TeachersPage } from './TeachersPage';
import { StudentProfileForm } from './components/StudentProfileForm';

const teacher: User = {
  id: 't',
  username: 'teacher',
  realName: '合成教师',
  email: 'teacher@example.edu',
  role: 'TEACHER',
  status: 'ACTIVE',
  teacherApprovalStatus: 'APPROVED',
};
const applicant: User = {
  id: 'p',
  username: 'pending',
  email: 'p@example.edu',
  role: 'STUDENT',
  status: 'ACTIVE',
  teacherApprovalStatus: 'PENDING',
};
const student: User = {
  id: 'u',
  username: 'student',
  email: 's@example.edu',
  role: 'STUDENT',
  status: 'ACTIVE',
  studentNo: '123',
  realName: '学生',
  className: '一班',
};
const course = { id: 'c', name: '课程', teacherId: 't' };
const classroom = {
  id: 's',
  courseId: 'c',
  courseName: '课程',
  teacherId: 't',
  teacherName: '合成教师',
  className: '一班',
  room: 'R',
  startsAt: '2020-01-01T01:02:03.123456+00:00',
  endsAt: '2020-01-01T02:02:03.123456+00:00',
  scheduledUserIds: [],
};
const dataset = (): WorkspaceData => ({
  users: [
    teacher,
    applicant,
    student,
    { ...teacher, id: 'disabled', username: 'disabled', status: 'DISABLED' },
  ],
  sessions: [classroom],
  records: [],
});
const changed = vi.fn(async () => {});
beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset());
  changed.mockClear();
  mocks.courses.mockResolvedValue([course]);
  mocks.applications.mockResolvedValue([
    {
      id: 'a',
      userId: 'p',
      status: 'PENDING',
      submittedAt: '2026-01-01T00:00:00Z',
      reviewedAt: null,
      reason: null,
    },
  ]);
  mocks.saveCourse.mockResolvedValue(course);
  mocks.saveSession.mockResolvedValue(classroom);
  mocks.saveStudent.mockResolvedValue(student);
  mocks.review.mockResolvedValue({ id: 'a', userId: 'p', status: 'APPROVED' });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
});
afterEach(cleanup);
const field = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const submit = () =>
  fireEvent.submit(screen.getByRole('button', { name: '确认提交' }).closest('form')!);

it('creates a course using only approved enabled teachers and waits for the write receipt', async () => {
  render(<AcademicPage data={dataset()} changed={changed} />);
  fireEvent.click(await screen.findByRole('button', { name: '新建课程' }));
  field('课程名称', ' 新课程 ');
  expect(screen.queryByRole('option', { name: /disabled/ })).toBeNull();
  expect(screen.queryByRole('option', { name: /pending/ })).toBeNull();
  field('默认教师', 't');
  submit();
  await waitFor(() =>
    expect(mocks.saveCourse).toHaveBeenCalledWith({ name: '新课程', teacherId: 't' }, undefined),
  );
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
});
it('edits a course without rewriting existing classroom teacher or times', async () => {
  render(<AcademicPage data={dataset()} changed={changed} />);
  fireEvent.click(await screen.findByRole('button', { name: '编辑课程 课程' }));
  field('课程名称', '更名');
  submit();
  await waitFor(() =>
    expect(mocks.saveCourse).toHaveBeenCalledWith({ name: '更名', teacherId: 't' }, 'c'),
  );
  expect(mocks.saveSession).not.toHaveBeenCalled();
});
it('locks historical classroom scope and preserves timestamp precision when changing room', async () => {
  render(<AcademicPage data={dataset()} changed={changed} />);
  fireEvent.click(screen.getByRole('button', { name: '课堂会话' }));
  fireEvent.click(await screen.findByRole('button', { name: '编辑课堂 课程 一班' }));
  expect((screen.getByLabelText('开始时间') as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByLabelText('课程') as HTMLSelectElement).disabled).toBe(true);
  expect((screen.getByLabelText('实际任课教师') as HTMLSelectElement).disabled).toBe(true);
  field('教室', '新教室');
  submit();
  await waitFor(() =>
    expect(mocks.saveSession).toHaveBeenCalledWith(
      {
        courseId: 'c',
        teacherId: 't',
        startsAt: classroom.startsAt,
        endsAt: classroom.endsAt,
        room: '新教室',
        className: '一班',
      },
      's',
    ),
  );
});
it('rejects reversed time ranges before sending and converts local input to timezone timestamps', async () => {
  render(<AcademicPage data={{ ...dataset(), sessions: [] }} changed={changed} />);
  await screen.findByRole('button', { name: '编辑课程 课程' });
  fireEvent.click(screen.getByRole('button', { name: '课堂会话' }));
  fireEvent.click(screen.getByRole('button', { name: '新建课堂' }));
  field('课程', 'c');
  field('开始时间', '2030-02-01T11:00');
  field('结束时间', '2030-02-01T10:00');
  field('教室', 'R');
  field('班级', '二班');
  submit();
  expect(await screen.findByRole('alert')).toHaveProperty(
    'textContent',
    '结束时间必须晚于开始时间。',
  );
  expect(mocks.saveSession).not.toHaveBeenCalled();
  field('结束时间', '2030-02-01T12:00');
  submit();
  await waitFor(() => expect(mocks.saveSession).toHaveBeenCalled());
  expect(mocks.saveSession.mock.calls[0][0]).toEqual({
    courseId: 'c',
    startsAt: new Date('2030-02-01T11:00').toISOString(),
    endsAt: new Date('2030-02-01T12:00').toISOString(),
    room: 'R',
    className: '二班',
  });
});
it('keeps the classroom form and values on a server lock conflict', async () => {
  mocks.saveSession.mockRejectedValue(new Error('课堂已锁定，请重新读取'));
  render(<AcademicPage data={dataset()} changed={changed} />);
  fireEvent.click(screen.getByRole('button', { name: '课堂会话' }));
  fireEvent.click(await screen.findByRole('button', { name: '编辑课堂 课程 一班' }));
  field('教室', '保留输入');
  submit();
  expect((await screen.findByRole('alert')).textContent).toContain('课堂已锁定');
  expect((screen.getByLabelText('教室') as HTMLInputElement).value).toBe('保留输入');
  expect(changed).not.toHaveBeenCalled();
});
it.each(['批准', '驳回'])(
  'confirms %s with a review reason and reloads user roles',
  async (choice) => {
    render(<TeachersPage users={dataset().users} changed={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: choice }));
    field('审核说明（选填）', '核对完成');
    submit();
    await waitFor(() =>
      expect(mocks.review).toHaveBeenCalledWith('a', {
        decision: choice === '批准' ? 'APPROVED' : 'REJECTED',
        reason: '核对完成',
      }),
    );
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  },
);
it('shows concurrent approval failure without pretending success', async () => {
  mocks.review.mockRejectedValue(new Error('申请已处理'));
  render(<TeachersPage users={dataset().users} changed={changed} />);
  fireEvent.click(await screen.findByRole('button', { name: '批准' }));
  submit();
  expect((await screen.findByRole('alert')).textContent).toContain('申请已处理');
  expect(changed).not.toHaveBeenCalled();
});
it('clears optional student fields explicitly and keeps identity fields out of the request', async () => {
  render(<StudentProfileForm user={student} close={vi.fn()} saved={changed} />);
  field('学号', '');
  field('姓名', '新姓名');
  submit();
  await waitFor(() =>
    expect(mocks.saveStudent).toHaveBeenCalledWith('u', {
      studentNo: null,
      realName: '新姓名',
      className: '一班',
    }),
  );
});
it('blocks duplicate clicks and closing while saving, and retains a failed student form', async () => {
  let reject!: (reason: Error) => void;
  mocks.saveStudent.mockReturnValue(
    new Promise((_resolve, fail) => {
      reject = fail;
    }),
  );
  const close = vi.fn();
  render(<StudentProfileForm user={student} close={close} saved={changed} />);
  const form = screen.getByRole('button', { name: '确认提交' }).closest('form')!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(mocks.saveStudent).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(close).not.toHaveBeenCalled();
  reject(new Error('学号已存在'));
  expect((await screen.findByRole('alert')).textContent).toContain('学号已存在');
  expect((screen.getByLabelText('学号') as HTMLInputElement).value).toBe('123');
});
it('does not silently replace a failed list with successful empty results', async () => {
  mocks.applications.mockRejectedValue(new Error('无权访问'));
  render(<TeachersPage users={dataset().users} changed={changed} />);
  expect((await screen.findByRole('alert')).textContent).toContain('无权访问');
  expect(mocks.review).not.toHaveBeenCalled();
});
