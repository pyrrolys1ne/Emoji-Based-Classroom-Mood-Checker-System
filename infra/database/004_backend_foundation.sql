-- 保留历史记录；新增身份、教师审批、会话与请求幂等结构。
ALTER TABLE app_user ADD COLUMN student_no VARCHAR(50) UNIQUE;
ALTER TABLE app_user ADD COLUMN real_name VARCHAR(100);
ALTER TABLE app_user ADD COLUMN class_name VARCHAR(100);
ALTER TABLE app_user ADD CONSTRAINT student_no_nonempty
    CHECK (student_no IS NULL OR length(btrim(student_no)) > 0);
ALTER TABLE app_user ADD CONSTRAINT real_name_nonempty
    CHECK (real_name IS NULL OR length(btrim(real_name)) > 0);
ALTER TABLE app_user ADD CONSTRAINT user_class_nonempty
    CHECK (class_name IS NULL OR length(btrim(class_name)) > 0);

CREATE TABLE teacher_application (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES app_user(id),
    status VARCHAR(10) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by UUID REFERENCES app_user(id),
    reason VARCHAR(500),
    CONSTRAINT teacher_review_state CHECK (
        (status = 'PENDING' AND reviewed_at IS NULL AND reviewed_by IS NULL)
        OR (status <> 'PENDING' AND reviewed_at IS NOT NULL)
    )
);
-- 旧库已有教师保留既有授权；新增申请须由业务服务审核后授予角色。
INSERT INTO teacher_application (user_id, status, reviewed_at)
    SELECT id, 'APPROVED', now() FROM app_user WHERE role = 'TEACHER';

CREATE TABLE user_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_user(id),
    token_hash VARCHAR(64) NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    CONSTRAINT user_session_time_order CHECK (expires_at > created_at)
);
CREATE INDEX user_session_user_idx ON user_session(user_id);

CREATE TABLE ws_ticket (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES user_session(id),
    token_hash VARCHAR(64) NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    CONSTRAINT ws_ticket_time_order CHECK (
        expires_at > created_at AND expires_at <= created_at + INTERVAL '30 seconds'
    )
);
CREATE INDEX ws_ticket_session_idx ON ws_ticket(session_id);

ALTER TABLE emoji_record ADD COLUMN simulated BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE emoji_record ADD COLUMN idempotency_key VARCHAR(100);
ALTER TABLE emoji_record ADD COLUMN request_hash VARCHAR(64);
ALTER TABLE emoji_record ADD CONSTRAINT record_idempotency_pair CHECK (
    (idempotency_key IS NULL AND request_hash IS NULL)
    OR (idempotency_key IS NOT NULL AND length(btrim(idempotency_key)) > 0
        AND request_hash IS NOT NULL AND request_hash ~ '^[0-9a-f]{64}$')
);
ALTER TABLE emoji_record ADD CONSTRAINT ai_anonymous CHECK (source <> 'AI' OR user_id IS NULL);
ALTER TABLE emoji_record ADD CONSTRAINT ai_basic_emotion CHECK (
    source <> 'AI' OR emotion NOT IN ('FOCUSED', 'CONFUSED')
);
ALTER TABLE emoji_record ADD CONSTRAINT ai_device_required CHECK (
    source <> 'AI' OR (device_id IS NOT NULL AND length(btrim(device_id)) > 0)
);
ALTER TABLE emoji_record ADD CONSTRAINT simulated_ai_only CHECK (NOT simulated OR source = 'AI');
ALTER TABLE emoji_record ADD CONSTRAINT inference_provider_known CHECK (
    inference_provider IS NULL OR inference_provider IN ('DeepSeek', 'DeepFace')
);
CREATE UNIQUE INDEX emoji_ai_idempotency_idx ON emoji_record(idempotency_key)
    WHERE source = 'AI' AND idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX emoji_manual_idempotency_idx ON emoji_record(user_id, idempotency_key)
    WHERE source = 'MANUAL' AND idempotency_key IS NOT NULL;
