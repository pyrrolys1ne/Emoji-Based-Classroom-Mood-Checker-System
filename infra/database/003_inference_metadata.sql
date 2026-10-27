-- 远程模型的自评分与传统分类分数需要在记录和导出时区分。
ALTER TABLE emoji_record ADD COLUMN inference_provider VARCHAR(30);
ALTER TABLE emoji_record ADD COLUMN confidence_kind VARCHAR(30)
    CHECK (confidence_kind IN ('self_reported', 'model_score'));
ALTER TABLE emoji_record ADD CONSTRAINT deepseek_score_kind
    CHECK (inference_provider IS DISTINCT FROM 'DeepSeek' OR confidence_kind IS NOT DISTINCT FROM 'self_reported');
