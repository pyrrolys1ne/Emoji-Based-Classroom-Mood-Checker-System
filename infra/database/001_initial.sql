-- PostgreSQL 初始结构。仅在空数据库执行；后续结构变更请新增迁移脚本。
CREATE TYPE user_role AS ENUM ('STUDENT', 'TEACHER', 'ADMIN');
CREATE TYPE user_status AS ENUM ('ACTIVE', 'DISABLED');
CREATE TYPE emotion_type AS ENUM ('HAPPY', 'FOCUSED', 'NEUTRAL', 'CONFUSED', 'SAD');
CREATE TYPE record_source AS ENUM ('MANUAL', 'AI');

CREATE TABLE app_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role user_role NOT NULL DEFAULT 'STUDENT',
    email VARCHAR(254) NOT NULL UNIQUE,
    status user_status NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE course (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(150) NOT NULL,
    teacher_id UUID NOT NULL REFERENCES app_user(id)
);

CREATE TABLE class_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id UUID NOT NULL REFERENCES course(id),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    room VARCHAR(100) NOT NULL,
    class_name VARCHAR(100) NOT NULL,
    CONSTRAINT session_time_order CHECK (ends_at > starts_at)
);

CREATE TABLE schedule_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES class_session(id),
    user_id UUID NOT NULL REFERENCES app_user(id),
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, user_id)
);

CREATE TABLE emoji_record (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES app_user(id),
    session_id UUID NOT NULL REFERENCES class_session(id),
    emotion emotion_type NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source record_source NOT NULL,
    confidence DOUBLE PRECISION,
    device_id VARCHAR(100),
    CONSTRAINT confidence_range CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT ai_confidence_required CHECK (source <> 'AI' OR confidence IS NOT NULL),
    CONSTRAINT manual_user_required CHECK (source <> 'MANUAL' OR user_id IS NOT NULL)
);

CREATE INDEX emoji_session_time_idx ON emoji_record(session_id, recorded_at DESC);
CREATE INDEX emoji_user_time_idx ON emoji_record(user_id, recorded_at DESC);
CREATE INDEX session_course_time_idx ON class_session(course_id, starts_at);

CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id UUID REFERENCES app_user(id),
    action VARCHAR(100) NOT NULL,
    target_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 不创建默认管理员或明文密码；管理员初始化与盐值哈希交由后续受控脚本。
-- 本结构不存储原始人脸图片、视频或人脸特征。
