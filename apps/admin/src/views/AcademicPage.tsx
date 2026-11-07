import { useState } from 'react';
import type {
  ClassSession,
  Course,
  CourseRequest,
  SessionRequest,
  WorkspaceData,
} from '@mood/contracts';
import { useManagementList, useManagementAction } from '../controllers/useManagement';
import { eligibleTeacher, localDateTime, sessionLocked } from '../models/management';
import {
  canManage,
  managementNotice,
  managementRepository as repo,
} from '../repositories/managementRepository';
import { ManagementForm } from './components/ManagementForm';

export function AcademicPage({
  data,
  changed,
}: {
  data: WorkspaceData;
  changed: () => Promise<void>;
}) {
  const list = useManagementList(repo.courses);
  const [tab, setTab] = useState<'courses' | 'sessions'>('courses');
  const [editing, setEditing] = useState<
    { kind: 'courses'; item?: Course } | { kind: 'sessions'; item?: ClassSession } | null
  >(null);
  const [message, setMessage] = useState('');
  const teachers = data.users.filter(eligibleTeacher);
  const ready = canManage && !list.loading && !list.error;
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>课程与课堂维护</h2>
          <p>课程默认教师与每次课堂任课人分别管理</p>
        </div>
        <div className="management-actions">
          <button
            className="button secondary"
            disabled={!canManage || list.loading}
            onClick={() => void Promise.all([list.refresh(), changed()])}
          >
            刷新资料
          </button>
          <button
            className="button"
            disabled={!ready || !teachers.length || (tab === 'sessions' && !list.items.length)}
            onClick={() => setEditing({ kind: tab })}
          >
            {tab === 'courses' ? '新建课程' : '新建课堂'}
          </button>
        </div>
      </div>
      {!canManage ? (
        <p className="management-note">{managementNotice}</p>
      ) : (
        <>
          <div className="filters" role="group" aria-label="维护内容">
            <button
              className={`button ${tab === 'courses' ? '' : 'secondary'}`}
              aria-pressed={tab === 'courses'}
              onClick={() => setTab('courses')}
            >
              课程目录
            </button>
            <button
              className={`button ${tab === 'sessions' ? '' : 'secondary'}`}
              aria-pressed={tab === 'sessions'}
              onClick={() => setTab('sessions')}
            >
              课堂会话
            </button>
          </div>
          {!teachers.length && (
            <p className="management-note">
              暂无启用且已批准的教师，请先到<a href="#teachers">教师审批</a>处理申请。
            </p>
          )}
          {message && (
            <p className="management-note success-message" role="status">
              {message}
            </p>
          )}
          {list.error && (
            <p className="management-note error" role="alert">
              {list.error}（请刷新资料后重试）
            </p>
          )}
          {list.loading ? (
            <p className="empty">正在加载课程…</p>
          ) : tab === 'courses' ? (
            !list.items.length ? (
              <p className="empty">暂无课程，请先新建课程</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>课程</th>
                      <th>默认教师</th>
                      <th>课堂数</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.items.map((course) => (
                      <tr key={course.id}>
                        <td>{course.name}</td>
                        <td>
                          {data.users.find((u) => u.id === course.teacherId)?.realName ||
                            data.users.find((u) => u.id === course.teacherId)?.username ||
                            '原任课教师'}
                        </td>
                        <td>{data.sessions.filter((s) => s.courseId === course.id).length}</td>
                        <td>
                          <button
                            className="text-button"
                            disabled={!ready}
                            aria-label={`编辑课程 ${course.name}`}
                            onClick={() => setEditing({ kind: 'courses', item: course })}
                          >
                            编辑课程
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          ) : !data.sessions.length ? (
            <p className="empty">暂无课堂，请创建课堂后安排学生</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>课程 / 班级</th>
                    <th>实际任课教师</th>
                    <th>时间 / 教室</th>
                    <th>学生 / 状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sessions.map((session) => {
                    const locked = sessionLocked(
                      session,
                      data.records.some((r) => r.sessionId === session.id),
                    );
                    return (
                      <tr key={session.id}>
                        <td>
                          {session.courseName}
                          <small>{session.className}</small>
                        </td>
                        <td>{session.teacherName}</td>
                        <td>
                          {new Date(session.startsAt).toLocaleString('zh-CN')}—
                          {new Date(session.endsAt).toLocaleTimeString('zh-CN')}
                          <small>{session.room}</small>
                        </td>
                        <td>
                          {session.scheduledUserIds.length} 人
                          <small>
                            {locked
                              ? '已开始或有记录，仅可修改教室与班级'
                              : '可调整课程、教师与时间'}
                          </small>
                        </td>
                        <td>
                          <button
                            className="text-button"
                            disabled={!ready}
                            aria-label={`编辑课堂 ${session.courseName} ${session.className}`}
                            onClick={() => setEditing({ kind: 'sessions', item: session })}
                          >
                            编辑课堂
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {tab === 'sessions' && (
            <p className="management-note">
              新课堂名单默认为空；创建后到<a href="#sessions">课堂安排</a>
              添加学生，修改学生所属班级不会自动安排名单。
            </p>
          )}
        </>
      )}
      {editing &&
        (editing.kind === 'courses' ? (
          <CourseForm
            course={editing.item}
            data={data}
            close={() => setEditing(null)}
            saved={async () => {
              setEditing(null);
              setMessage('课程已保存；已有课堂的实际任课教师保持原值。');
              await Promise.all([list.refresh(), changed()]);
            }}
          />
        ) : (
          <SessionForm
            session={editing.item}
            courses={list.items}
            data={data}
            close={() => setEditing(null)}
            saved={async () => {
              setEditing(null);
              setMessage('课堂已保存，可到课堂安排维护学生名单。');
              await changed();
            }}
          />
        ))}
    </section>
  );
}

function CourseForm({
  course,
  data,
  close,
  saved,
}: {
  course?: Course;
  data: WorkspaceData;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const [form, setForm] = useState<CourseRequest>({
    name: course?.name || '',
    teacherId: course?.teacherId || '',
  });
  const action = useManagementAction();
  const teachers = data.users.filter(eligibleTeacher);
  return (
    <ManagementForm
      title={course ? '编辑课程' : '新建课程'}
      busy={action.busy}
      error={action.error}
      close={close}
      submit={() =>
        void action.run(async () => {
          await repo.saveCourse({ ...form, name: form.name.trim() }, course?.id);
          await saved();
        })
      }
    >
      <label>
        课程名称
        <input
          required
          maxLength={150}
          pattern=".*\S.*"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
      </label>
      <label>
        默认教师
        <select
          required
          value={form.teacherId}
          onChange={(e) => setForm({ ...form, teacherId: e.target.value })}
        >
          <option value="">请选择已批准教师</option>
          {form.teacherId && !teachers.some((t) => t.id === form.teacherId) && (
            <option value={form.teacherId} disabled>
              原教师不可用，请重新选择
            </option>
          )}
          {teachers.map((t) => (
            <option key={t.id} value={t.id}>
              {t.realName || t.username} · {t.username}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">更换默认教师只影响后续课堂的默认选择，不转移已有课堂及历史权限。</p>
    </ManagementForm>
  );
}

function SessionForm({
  session,
  courses,
  data,
  close,
  saved,
}: {
  session?: ClassSession;
  courses: Course[];
  data: WorkspaceData;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const [form, setForm] = useState({
    courseId: session?.courseId || '',
    teacherId: session?.teacherId || '',
    startsAt: session ? localDateTime(session.startsAt) : '',
    endsAt: session ? localDateTime(session.endsAt) : '',
    room: session?.room || '',
    className: session?.className || '',
  });
  const action = useManagementAction();
  const [error, setError] = useState('');
  const locked =
    !!session &&
    sessionLocked(
      session,
      data.records.some((r) => r.sessionId === session.id),
    );
  const teachers = data.users.filter(eligibleTeacher);
  const submit = async () => {
    setError('');
    if (!form.startsAt || !form.endsAt || Date.parse(form.endsAt) <= Date.parse(form.startsAt)) {
      setError('结束时间必须晚于开始时间。');
      return;
    }
    // 未改动的时间使用原时间戳，避免分钟输入截断秒和微秒后误改锁定课堂。
    const time = (field: 'startsAt' | 'endsAt') =>
      session && (locked || form[field] === localDateTime(session[field]))
        ? session[field]
        : new Date(form[field]).toISOString();
    const body: SessionRequest = {
      courseId: form.courseId,
      startsAt: time('startsAt'),
      endsAt: time('endsAt'),
      room: form.room.trim(),
      className: form.className.trim(),
      ...(form.teacherId ? { teacherId: form.teacherId } : {}),
    };
    await action.run(async () => {
      await repo.saveSession(body, session?.id);
      await saved();
    });
  };
  return (
    <ManagementForm
      title={session ? '编辑课堂' : '新建课堂'}
      busy={action.busy}
      error={error || action.error}
      close={close}
      submit={() => void submit()}
    >
      {locked && (
        <p className="muted">
          该课堂已开始或存在记录，仅可修改教室与班级；并发变化仍由服务端校验。
        </p>
      )}
      <label>
        课程
        <select
          required
          disabled={locked}
          value={form.courseId}
          onChange={(e) => setForm({ ...form, courseId: e.target.value })}
        >
          <option value="">请选择课程</option>
          {courses.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        实际任课教师
        <select
          disabled={locked}
          value={form.teacherId}
          onChange={(e) => setForm({ ...form, teacherId: e.target.value })}
        >
          <option value="">{session ? '保留原任课教师' : '使用所选课程的默认教师'}</option>
          {form.teacherId && !teachers.some((t) => t.id === form.teacherId) && (
            <option value={form.teacherId} disabled>
              {session?.teacherName || '原教师'}
            </option>
          )}
          {teachers.map((t) => (
            <option key={t.id} value={t.id}>
              {t.realName || t.username} · {t.username}
            </option>
          ))}
        </select>
      </label>
      <label>
        开始时间
        <input
          type="datetime-local"
          required
          disabled={locked}
          value={form.startsAt}
          onChange={(e) => setForm({ ...form, startsAt: e.target.value })}
        />
      </label>
      <label>
        结束时间
        <input
          type="datetime-local"
          required
          disabled={locked}
          value={form.endsAt}
          onChange={(e) => setForm({ ...form, endsAt: e.target.value })}
        />
      </label>
      <label>
        教室
        <input
          required
          maxLength={100}
          pattern=".*\S.*"
          value={form.room}
          onChange={(e) => setForm({ ...form, room: e.target.value })}
        />
      </label>
      <label>
        班级
        <input
          required
          maxLength={100}
          pattern=".*\S.*"
          value={form.className}
          onChange={(e) => setForm({ ...form, className: e.target.value })}
        />
      </label>
      <p className="muted">输入时间按浏览器本地时区解释，提交时转换为带时区时间。</p>
    </ManagementForm>
  );
}
