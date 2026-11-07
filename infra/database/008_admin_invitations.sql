-- 管理员注册使用有时效的一次性邀请码，仅保存摘要。
CREATE TABLE admin_invitation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    created_by UUID REFERENCES app_user(id),
    used_at TIMESTAMPTZ,
    used_by UUID REFERENCES app_user(id),
    CONSTRAINT admin_invitation_hash_check CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT admin_invitation_time_order CHECK (expires_at > created_at),
    CONSTRAINT admin_invitation_usage_check CHECK (
        (used_at IS NULL AND used_by IS NULL) OR
        (used_at IS NOT NULL AND used_by IS NOT NULL AND used_at >= created_at AND used_at < expires_at)
    )
);
