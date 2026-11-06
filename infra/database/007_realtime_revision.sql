-- 课堂版本随同业务事务更新，多个后端进程读取相同的已提交变更。
ALTER TABLE class_session ADD COLUMN revision BIGINT NOT NULL DEFAULT 0;
ALTER TABLE class_session ADD CONSTRAINT session_revision_check CHECK (revision >= 0);

CREATE FUNCTION bump_classroom_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.revision := OLD.revision + 1;
    RETURN NEW;
END $$;
CREATE TRIGGER classroom_revision BEFORE UPDATE ON class_session
    FOR EACH ROW EXECUTE FUNCTION bump_classroom_revision();

CREATE FUNCTION bump_record_classroom() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous_id UUID; current_id UUID;
BEGIN
    IF TG_OP <> 'INSERT' AND NOT OLD.simulated THEN previous_id := OLD.session_id; END IF;
    IF TG_OP <> 'DELETE' AND NOT NEW.simulated THEN current_id := NEW.session_id; END IF;
    -- 模拟数据不改变正式版本，隔离开发环境仍通过记录计数通知。
    PERFORM id FROM class_session WHERE id IN (previous_id, current_id) ORDER BY id FOR UPDATE;
    UPDATE class_session SET revision = revision + 1 WHERE id IN (previous_id, current_id);
    RETURN NULL;
END $$;
CREATE TRIGGER record_classroom_revision AFTER INSERT OR UPDATE OR DELETE ON emoji_record
    FOR EACH ROW EXECUTE FUNCTION bump_record_classroom();

CREATE FUNCTION bump_schedule_classroom() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous_id UUID; current_id UUID;
BEGIN
    IF TG_OP <> 'INSERT' THEN previous_id := OLD.session_id; END IF;
    IF TG_OP <> 'DELETE' THEN current_id := NEW.session_id; END IF;
    PERFORM id FROM class_session WHERE id IN (previous_id, current_id) ORDER BY id FOR UPDATE;
    UPDATE class_session SET revision = revision + 1 WHERE id IN (previous_id, current_id);
    RETURN NULL;
END $$;
CREATE TRIGGER schedule_classroom_revision AFTER INSERT OR UPDATE OR DELETE ON schedule_user
    FOR EACH ROW EXECUTE FUNCTION bump_schedule_classroom();

CREATE FUNCTION bump_course_classrooms() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.name IS DISTINCT FROM OLD.name THEN
        PERFORM id FROM class_session WHERE course_id = NEW.id ORDER BY id FOR UPDATE;
        UPDATE class_session SET revision = revision + 1 WHERE course_id = NEW.id;
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER course_classroom_revision AFTER UPDATE ON course
    FOR EACH ROW EXECUTE FUNCTION bump_course_classrooms();

CREATE FUNCTION bump_user_classrooms() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.username, NEW.student_no, NEW.real_name, NEW.class_name, NEW.status, NEW.role)
       IS DISTINCT FROM ROW(OLD.username, OLD.student_no, OLD.real_name, OLD.class_name, OLD.status, OLD.role) THEN
        PERFORM id FROM class_session WHERE teacher_id = NEW.id
            OR id IN (SELECT session_id FROM schedule_user WHERE user_id = NEW.id)
            OR id IN (SELECT session_id FROM emoji_record WHERE user_id = NEW.id)
            ORDER BY id FOR UPDATE;
        UPDATE class_session SET revision = revision + 1 WHERE teacher_id = NEW.id
            OR id IN (SELECT session_id FROM schedule_user WHERE user_id = NEW.id)
            OR id IN (SELECT session_id FROM emoji_record WHERE user_id = NEW.id);
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER user_classroom_revision AFTER UPDATE ON app_user
    FOR EACH ROW EXECUTE FUNCTION bump_user_classrooms();
