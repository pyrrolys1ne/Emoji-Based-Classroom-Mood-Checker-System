-- 课堂独立保存任课教师，课程默认教师变更不改写历史课堂范围。
ALTER TABLE class_session ADD COLUMN teacher_id UUID REFERENCES app_user(id);
UPDATE class_session AS classroom
    SET teacher_id = course.teacher_id
    FROM course WHERE classroom.course_id = course.id;
ALTER TABLE class_session ALTER COLUMN teacher_id SET NOT NULL;
CREATE INDEX session_teacher_time_idx ON class_session(teacher_id, starts_at);

-- 受控初始化批次只允许提交一次，失败时随课程、课堂和审计共同回滚。
CREATE TABLE classroom_import (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id UUID NOT NULL REFERENCES app_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
