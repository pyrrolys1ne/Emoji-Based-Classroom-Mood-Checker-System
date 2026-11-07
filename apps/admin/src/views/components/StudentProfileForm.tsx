import { useState } from 'react';
import type { User } from '@mood/contracts';
import { useManagementAction } from '../../controllers/useManagement';
import { managementRepository as repo } from '../../repositories/managementRepository';
import { ManagementForm } from './ManagementForm';

export function StudentProfileForm({
  user,
  close,
  saved,
}: {
  user: User;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const [form, setForm] = useState({
    studentNo: user.studentNo || '',
    realName: user.realName || '',
    className: user.className || '',
  });
  const action = useManagementAction();
  return (
    <ManagementForm
      title={`编辑学生资料 · ${user.username}`}
      busy={action.busy}
      error={action.error}
      close={close}
      submit={() =>
        void action.run(async () => {
          await repo.saveStudent(user.id, {
            studentNo: form.studentNo.trim() || null,
            realName: form.realName.trim() || null,
            className: form.className.trim() || null,
          });
          await saved();
        })
      }
    >
      <p className="muted">
        留空会清除该字段。学号必须唯一；资料修改不改变身份、账号状态或课堂名单。
      </p>
      <label>
        学号
        <input
          maxLength={50}
          value={form.studentNo}
          onChange={(e) => setForm({ ...form, studentNo: e.target.value })}
        />
      </label>
      <label>
        姓名
        <input
          maxLength={100}
          value={form.realName}
          onChange={(e) => setForm({ ...form, realName: e.target.value })}
        />
      </label>
      <label>
        所属班级
        <input
          maxLength={100}
          value={form.className}
          onChange={(e) => setForm({ ...form, className: e.target.value })}
        />
      </label>
    </ManagementForm>
  );
}
