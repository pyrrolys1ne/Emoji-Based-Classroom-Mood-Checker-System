import type {
  Course,
  CourseRequest,
  SessionRequest,
  ClassSession,
  StudentProfileRequest,
  TeacherApplication,
  TeacherReviewRequest,
  User,
} from '@mood/contracts';
import { isDemo, isIntegration, request } from './http';

export const canManage = !isDemo && !isIntegration;
export const managementNotice =
  '数据维护需要连接正式后端 API；演示和独立联调模式不提供这些写入操作。';

async function call<T>(
  path: string,
  init: RequestInit,
  valid: (value: unknown) => boolean,
): Promise<T> {
  if (!canManage) throw new Error(managementNotice);
  const value = await request<T>(path, init);
  if (!valid(value)) throw new Error('服务回执格式无效，请刷新核对结果，避免重复提交。');
  return value;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object';
const identified = (v: unknown): v is Record<string, unknown> =>
  object(v) && typeof v.id === 'string' && v.id.length > 0;
const course = (v: unknown) =>
  identified(v) && typeof v.name === 'string' && typeof v.teacherId === 'string';
const application = (v: unknown) =>
  identified(v) &&
  typeof v.userId === 'string' &&
  ['PENDING', 'APPROVED', 'REJECTED'].includes(String(v.status));
const session = (v: unknown) =>
  identified(v) && typeof v.courseId === 'string' && Array.isArray(v.scheduledUserIds);
const user = (v: unknown) =>
  identified(v) && v.role === 'STUDENT' && typeof v.username === 'string';
const write = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const managementRepository = {
  courses: (signal?: AbortSignal) =>
    call<Course[]>('/admin/courses', { signal }, (v) => Array.isArray(v) && v.every(course)),
  applications: (signal?: AbortSignal) =>
    call<TeacherApplication[]>(
      '/admin/teacher-applications',
      { signal },
      (v) => Array.isArray(v) && v.every(application),
    ),
  saveCourse: (body: CourseRequest, id?: string) =>
    call<Course>(
      `/admin/courses${id ? '/' + encodeURIComponent(id) : ''}`,
      write(id ? 'PUT' : 'POST', body),
      (v) => course(v) && (!id || (v as Course).id === id),
    ),
  saveSession: (body: SessionRequest, id?: string) =>
    call<ClassSession>(
      `/admin/sessions${id ? '/' + encodeURIComponent(id) : ''}`,
      write(id ? 'PUT' : 'POST', body),
      (v) => session(v) && (!id || (v as ClassSession).id === id),
    ),
  review: (id: string, body: TeacherReviewRequest) =>
    call<TeacherApplication>(
      `/admin/teacher-applications/${encodeURIComponent(id)}`,
      write('PUT', body),
      (v) =>
        application(v) &&
        (v as TeacherApplication).id === id &&
        (v as TeacherApplication).status === body.decision,
    ),
  saveStudent: (id: string, body: StudentProfileRequest) =>
    call<User>(
      `/admin/users/${encodeURIComponent(id)}/student-profile`,
      write('PUT', body),
      (v) => user(v) && (v as User).id === id,
    ),
};
