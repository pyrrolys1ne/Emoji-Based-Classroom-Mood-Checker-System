-- 已执行 001_initial.sql 的数据库需执行此迁移；不修改历史枚举含义。
ALTER TYPE emotion_type ADD VALUE IF NOT EXISTS 'ANGRY';
ALTER TYPE emotion_type ADD VALUE IF NOT EXISTS 'SURPRISED';
ALTER TYPE emotion_type ADD VALUE IF NOT EXISTS 'FEAR';
ALTER TYPE emotion_type ADD VALUE IF NOT EXISTS 'DISGUST';
-- 正式后端应默认拒绝模拟 AI 输入；联调数据仅保存在独立 SQLite。
