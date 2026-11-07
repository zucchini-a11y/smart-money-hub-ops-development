-- Development-only content for the next member Trading Academy lesson.
-- This migration is restricted to the isolated smh_test schema.
BEGIN;
SET LOCAL search_path TO smh_test;

DO $$
BEGIN
    IF current_schema() <> 'smh_test' THEN
        RAISE EXCEPTION 'Trading Academy lesson migration is Development-only (smh_test).';
    END IF;
END
$$;

INSERT INTO member_learning_lessons
    (lesson_key, title, summary, body_markdown, sequence, published, updated_at)
VALUES
    (
        'liquidity-and-equal-highs-lows',
        'Liquidity and equal highs and lows',
        'Study repeated swing levels as chart references without assuming hidden orders or a guaranteed reaction.',
        $lesson$
## What traders mean by liquidity

In Smart Money Concepts, traders use the word liquidity when discussing areas where orders may be concentrated. A price chart does not show every resting order, and a repeated level does not prove that stop orders are sitting there. Treat liquidity as an interpretation to study, not a fact you can see directly.

## Equal highs and equal lows

When several visible swing highs form near a similar price, traders may call that an equal-high area. Repeated swing lows can form an equal-low area. These are observable chart references. Price may approach, pass, reject, or ignore them; the pattern alone does not predict which outcome will happen.

## How to study the idea

1. Mark two or more visible swing highs or lows that sit near a similar level.
2. Describe the area as a reference zone, not as confirmed hidden orders.
3. Observe what price does around the zone without assuming a sweep or reversal.
4. Record the timeframe and the evidence that would change your description.

## Keep the distinction clear

The chart shows price and visible swings; it does not reveal every participant's orders or intent. A liquidity label is not an entry signal. Wait for your own confirmation and follow a defined risk plan.

**NO CONFIRMATION, NO ENTRY.**
$lesson$,
        4,
        TRUE,
        NOW()
    )
ON CONFLICT (lesson_key) DO UPDATE
SET title = EXCLUDED.title,
    summary = EXCLUDED.summary,
    body_markdown = EXCLUDED.body_markdown,
    sequence = EXCLUDED.sequence,
    published = TRUE,
    updated_at = NOW();

COMMIT;
