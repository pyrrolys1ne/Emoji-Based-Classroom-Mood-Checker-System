-- 接受与过滤均持久化幂等回执，阈值调整不改变已完成请求的结果。
CREATE TABLE ai_ingestion (
    idempotency_key VARCHAR(100) PRIMARY KEY,
    request_hash VARCHAR(64) NOT NULL,
    record_id UUID UNIQUE REFERENCES emoji_record(id),
    reason VARCHAR(30),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ai_ingestion_key_check CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,100}$'),
    CONSTRAINT ai_ingestion_hash_check CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ai_ingestion_outcome_check CHECK (
        (record_id IS NOT NULL AND reason IS NULL) OR
        (record_id IS NULL AND reason IS NOT NULL AND reason = 'LOW_CONFIDENCE')
    )
);

-- 保留已有 AI 记录及稳定请求键，手动记录使用独立的命名空间。
INSERT INTO ai_ingestion (idempotency_key, request_hash, record_id)
    SELECT idempotency_key, request_hash, id FROM emoji_record
    WHERE source = 'AI' AND idempotency_key IS NOT NULL;
