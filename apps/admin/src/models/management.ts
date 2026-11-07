import type { ClassSession, User } from '@mood/contracts';

export const eligibleTeacher = (user: User) =>
  user.role === 'TEACHER' && user.status === 'ACTIVE' && user.teacherApprovalStatus === 'APPROVED';
export const editableStudent = (user: User) =>
  user.role === 'STUDENT' && !user.teacherApprovalStatus;
export const sessionLocked = (session: ClassSession, recorded: boolean) =>
  recorded || Date.parse(session.startsAt) <= Date.now();
export function localDateTime(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
