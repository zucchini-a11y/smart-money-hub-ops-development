-- Development-only core Smart Money Concepts curriculum additions.
-- This migration is restricted to the isolated smh_test schema.
BEGIN;
SET LOCAL search_path TO smh_test;

DO $$
BEGIN
    IF current_schema() <> 'smh_test' THEN
        RAISE EXCEPTION 'Trading Academy curriculum migration is Development-only (smh_test).';
    END IF;
END
$$;

INSERT INTO member_learning_lessons
    (lesson_key, title, summary, body_markdown, sequence, published, updated_at)
VALUES
    (
        'order-blocks-in-context',
        'Order blocks: an analytical label',
        'Learn how some SMC frameworks describe a prior candle zone without treating it as proof of orders or a trade signal.',
        $lesson$
## What the term describes

Some Smart Money Concepts frameworks label the final opposing candle or small candle area before a strong price move as an order block. This is an analytical convention used to describe a chart pattern. A candlestick chart does not reveal who placed orders or prove that a bank or institution caused the move.

## Study the surrounding structure

1. Identify the visible candle area the framework is referring to.
2. Describe what price did after it, using the chart rather than a story about hidden participants.
3. Compare the area with the broader swing structure and nearby reference levels.
4. Record what evidence would make the label less useful or invalid for your analysis.

## Keep the label in perspective

Price can return to a marked area, pass through it, or never revisit it. The label does not guarantee support, resistance, or a reaction. It is not an entry signal.

**NO CONFIRMATION, NO ENTRY.**
$lesson$,
        5,
        TRUE,
        NOW()
    ),
    (
        'fair-value-gaps',
        'Fair value gaps and price imbalance',
        'Recognize a commonly used three-candle imbalance description while avoiding assumptions about what price must do next.',
        $lesson$
## The three-candle description

In one common SMC convention, a bullish fair value gap is the space between the first candle's high and the third candle's low when the third candle's low is above the first candle's high. A bearish example reverses that relationship. The middle candle is often the strongest candle in the sequence.

This is a chart-pattern definition, not proof that no transactions occurred in the area. Data source, timeframe, and candle construction can affect what appears on a chart.

## How to study it

1. Mark the first, middle, and third candles in order.
2. Compare the first candle's high with the third candle's low for a bullish example.
3. Describe the gap area only when the chosen chart shows one clearly.
4. Observe whether price revisits the area, without assuming that it must.

## No automatic outcome

A gap may be revisited, partly revisited, or left untouched. It does not predict a reversal or continuation and is not an entry signal.

**NO CONFIRMATION, NO ENTRY.**
$lesson$,
        6,
        TRUE,
        NOW()
    ),
    (
        'multi-timeframe-context',
        'Putting timeframes in context',
        'Compare broader price structure with closer detail without relying on a fixed timeframe recipe.',
        $lesson$
## Broad context and local detail

A wider chart can make larger swings easier to see. A closer chart can show smaller price movements inside those swings. Both views describe the same market at different levels of detail; the smaller view does not automatically override the wider one.

## A neutral review routine

1. Choose timeframes that fit your own study routine; there is no required pair for every trader.
2. Describe the broader swing sequence before examining smaller movements.
3. Note where the closer view agrees or conflicts with the broader description.
4. Record uncertainty rather than forcing the two views to agree.

## Avoid false precision

Changing timeframe changes the appearance of candles and swings. More detail is not the same as more certainty. A timeframe comparison is context, not a forecast or trade instruction.

**NO CONFIRMATION, NO ENTRY.**
$lesson$,
        7,
        TRUE,
        NOW()
    ),
    (
        'confirmation-and-risk-planning',
        'Confirmation, risk, and review',
        'Build a personal pre-decision checklist and record uncertainty without relying on a universal risk percentage.',
        $lesson$
## Define what you are waiting to observe

Before considering a trade idea, write down the evidence you would need to see and the evidence that would weaken your description. A concept such as BOS, CHoCH, an order block, or a gap is not confirmation on its own.

## Plan before acting

1. State the market condition you are observing in plain language.
2. Write the confirmation you personally require and what would invalidate the idea.
3. Decide in advance how you would limit exposure if you choose to trade; do not assume one percentage fits everyone.
4. If the evidence is unclear, record that and stand aside.
5. Review the observation afterward without judging the process only by the outcome.

## The learning standard

No setup is guaranteed. Protecting capital and following a considered plan matter more than taking every possible move. Education supports independent decisions; it does not provide personalized financial advice.

**NO CONFIRMATION, NO ENTRY.**
$lesson$,
        8,
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
