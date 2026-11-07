-- Development-only website lessons and member-owned progress.
-- Do not apply to Production; the script only permits schema smh_test.
BEGIN;
SET LOCAL search_path TO smh_test;

DO $$
BEGIN
    IF current_schema() <> 'smh_test' THEN
        RAISE EXCEPTION 'Website learning migration is Development-only (smh_test).';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS member_learning_lessons (
    lesson_key TEXT PRIMARY KEY CHECK (lesson_key ~ '^[a-z0-9-]{1,80}$'),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
    summary TEXT NOT NULL CHECK (length(summary) <= 500),
    body_markdown TEXT NOT NULL,
    sequence INTEGER NOT NULL UNIQUE CHECK (sequence > 0),
    published BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS member_learning_progress (
    clerk_user_id TEXT NOT NULL,
    lesson_key TEXT NOT NULL REFERENCES member_learning_lessons(lesson_key) ON DELETE RESTRICT,
    progress TEXT NOT NULL CHECK (progress IN ('in_progress', 'completed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (clerk_user_id, lesson_key),
    CHECK ((progress = 'completed' AND completed_at IS NOT NULL) OR progress = 'in_progress')
);

CREATE INDEX IF NOT EXISTS member_learning_progress_member_updated
    ON member_learning_progress(clerk_user_id, updated_at DESC);

INSERT INTO member_learning_lessons
    (lesson_key, title, summary, body_markdown, sequence)
VALUES
    (
        'orientation',
        'Start here: your learning journey',
        'Understand the learning routine, risk principles, and what to study next.',
        E'Welcome to Smart Money Hub. This learning journey is designed to help you understand markets, develop your analysis skills, and become a more independent trader.\n\n## How to learn\n\nStudy each lesson in order. Complete the practice activity when one is provided, ask questions when something is unclear, and take time to understand before moving on.\n\n## Risk and trading principles\n\nProtect your capital. No setup is guaranteed to make a profit. A Point of Interest is an area to observe, not an automatic entry. Do not chase price or force a trade.\n\n**NO CONFIRMATION, NO ENTRY.**\n\nToday is orientation. The next lesson is Understanding Market Structure.',
        1
    ),
    (
        'market-structure',
        'Understanding market structure',
        'Read the sequence of meaningful swing highs and swing lows before forming a view.',
        E'Market structure describes how price forms swing highs and swing lows over time. To understand direction, study the sequence of these swings rather than relying on a single candle.\n\nA single green or red candle does not determine market direction. Consider whether the sequence of significant swings supports a bullish, bearish, or ranging description.\n\n## Practice\n\n1. Choose one timeframe on your Gold (XAUUSD) chart.\n2. Describe whether the market is bullish, bearish, or ranging.\n3. Mark at least two significant swing highs and two significant swing lows.\n4. Explain how the sequence supports your description.\n\nDo not rush into looking for entries. Focus on reading structure first. **NO CONFIRMATION, NO ENTRY.**',
        2
    ),
    (
        'bos-and-choch',
        'Break of Structure and Change of Character',
        'Learn the basic distinction without treating either concept as an entry signal.',
        E'A Break of Structure (BOS) describes a break with the existing market structure. A Change of Character (CHoCH) describes a possible break against that structure.\n\nThese terms describe price structure; neither guarantees what price will do next or gives permission to enter a trade. Use them as observations, then wait for your own confirmation and follow your risk plan.\n\n**NO CONFIRMATION, NO ENTRY.**',
        3
    )
ON CONFLICT (lesson_key) DO NOTHING;

COMMIT;
