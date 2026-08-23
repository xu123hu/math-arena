-- ============================================================
-- 智学数研 · AI 管家化重构 · 数据库变更脚本（迭代17）
-- 生成日期：2026-08-14
-- 数据库：PostgreSQL 15（+ pgvector）
-- 说明：本脚本为幂等设计（IF NOT EXISTS），可直接在 math_arena 库执行。
--       error_records 的 FSRS 字段已在迭代16 落库，此处用 DO $$ 兼容性补齐。
-- ============================================================

-- 1) 学生画像表：AI 计算的学生标签 / 薄弱点排名 / 学习风格 / 当前阶段
CREATE TABLE IF NOT EXISTS student_profiles (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL UNIQUE REFERENCES users(id),
    tags            JSONB NOT NULL DEFAULT '[]',
    weak_point_rank JSONB NOT NULL DEFAULT '[]',
    learning_style  VARCHAR(16) NOT NULL DEFAULT 'practice',
    current_stage   VARCHAR(32) NOT NULL DEFAULT '',
    profile_card    TEXT,
    computed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2) 学习事件表：管家决策输入源（幂等键 + 处理状态 + 重试）
CREATE TABLE IF NOT EXISTS learning_events (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id),
    event_type      VARCHAR(64) NOT NULL,
    source_type     VARCHAR(32) NOT NULL,
    source_id       VARCHAR(64),
    payload         JSONB NOT NULL DEFAULT '{}',
    idempotency_key VARCHAR(128) UNIQUE,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    retry_count     INTEGER NOT NULL DEFAULT 0,
    processed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_learning_events_user_status ON learning_events(user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_learning_events_type_time  ON learning_events(event_type, created_at);

-- 3) AI 推荐记录表：每日任务 / 复习提醒 / 资源推荐 / 路径步骤 + 点击反馈
CREATE TABLE IF NOT EXISTS ai_recommendations (
    id            UUID PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id),
    kind          VARCHAR(32) NOT NULL,
    source        VARCHAR(32) NOT NULL,
    payload       JSONB NOT NULL DEFAULT '{}',
    llm_model     VARCHAR(64),
    user_feedback VARCHAR(16),
    shown_at      TIMESTAMPTZ,
    acted_at      TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_rec_user_kind_time ON ai_recommendations(user_id, kind, created_at);

-- 4) 试卷题库表：导入真题/模拟套卷 + 套卷题目
CREATE TABLE IF NOT EXISTS exam_papers (
    id               UUID PRIMARY KEY,
    title            VARCHAR(200) NOT NULL,
    source           VARCHAR(100),
    year             INTEGER,
    subject          VARCHAR(16) NOT NULL DEFAULT 'math',
    scope            VARCHAR(16) NOT NULL DEFAULT 'student',
    total_score      NUMERIC,
    duration_minutes INTEGER,
    structure        JSONB,
    status           VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_exam_papers_scope_year ON exam_papers(scope, year);

CREATE TABLE IF NOT EXISTS exam_paper_items (
    id         UUID PRIMARY KEY,
    paper_id   UUID NOT NULL REFERENCES exam_papers(id),
    item_no    INTEGER NOT NULL,
    q_type     VARCHAR(20) NOT NULL,
    stem       TEXT NOT NULL,
    options    JSONB,
    answer     TEXT NOT NULL,
    analysis   TEXT,
    kp_code    VARCHAR(32),
    difficulty VARCHAR(10) NOT NULL DEFAULT 'medium',
    score      NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_exam_paper_items_paper_no ON exam_paper_items(paper_id, item_no);

-- 5) 每日一题学情化：daily_questions 由「全站每天一题」改为「每生每天一题」
--    原表 date 唯一（全站共享），流水数据无业务保留价值（题目在 quizzes/quiz_items 中），安全重建。
DROP TABLE IF EXISTS daily_questions;
CREATE TABLE daily_questions (
    id         SERIAL PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users(id),
    date       DATE NOT NULL,
    quiz_id    UUID NOT NULL REFERENCES quizzes(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_daily_questions_user_date UNIQUE (user_id, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_questions_user ON daily_questions(user_id);

-- 6) error_records FSRS 字段兼容补齐（迭代16 已通过 Alembic 落库，此处幂等兜底）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='error_records' AND column_name='wrong_count') THEN
        ALTER TABLE error_records ADD COLUMN wrong_count INTEGER NOT NULL DEFAULT 1;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='error_records' AND column_name='fsrs_stability') THEN
        ALTER TABLE error_records ADD COLUMN fsrs_stability NUMERIC;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='error_records' AND column_name='fsrs_difficulty') THEN
        ALTER TABLE error_records ADD COLUMN fsrs_difficulty NUMERIC;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='error_records' AND column_name='fsrs_retrievability') THEN
        ALTER TABLE error_records ADD COLUMN fsrs_retrievability NUMERIC;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='error_records' AND column_name='fsrs_computed_at') THEN
        ALTER TABLE error_records ADD COLUMN fsrs_computed_at TIMESTAMPTZ;
    END IF;
END $$;
