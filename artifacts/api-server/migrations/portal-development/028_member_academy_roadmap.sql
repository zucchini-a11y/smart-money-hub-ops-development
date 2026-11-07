-- Development-only alignment of Academy lessons with the member-provided roadmap.
-- This migration is restricted to the isolated smh_test schema.
BEGIN;
SET LOCAL search_path TO smh_test;

DO $$
BEGIN
    IF current_schema() <> 'smh_test' THEN
        RAISE EXCEPTION 'Academy roadmap migration is Development-only (smh_test).';
    END IF;
END
$$;

UPDATE member_learning_lessons
SET summary = 'Follow Learn, Practise, Analyse, and Review using your stated H1/M5 and risk framework.',
    body_markdown = $lesson$
Welcome to the VAYDA Smart Money Hub Trading Academy. The goal is to understand the concept, practise it on charts, analyse Gold and other relevant markets, and review your understanding.

## The learning route

Use **Learn → Practise → Analyse → Review** in every lesson. Published lessons are readable in any order. Recorded progress still follows the study sequence.

## Our trading philosophy

These are your established rules for the curriculum:

- Higher-timeframe bias: **H1**.
- Entry timeframe: **M5**.
- Risk per trade: **2%**.
- Minimum planned risk-to-reward: **1:3**.
- Maximum daily loss: **3%**.
- Move to breakeven at **1:1**, according to your trade plan.
- No forced entries, FOMO, or revenge trading.
- No setup means no trade.

**NO CONFIRMATION, NO ENTRY.**

These are your stated plan values, not a guarantee or proof that a setup is valid.
$lesson$,
    updated_at = NOW()
WHERE lesson_key = 'orientation';

UPDATE member_learning_lessons
SET summary = 'Use H1 for higher-timeframe bias and M5 for entry-timeframe review without forcing agreement.',
    body_markdown = $lesson$
## H1 bias and M5 entry timeframe

Use H1 to describe your higher-timeframe bias from visible price structure. Use M5 as your entry timeframe to observe the evidence your plan requires. A timeframe label does not itself confirm a trade.

## Practise

1. On H1, mark clear swing highs and swing lows and describe the bias as bullish, bearish, ranging, or unclear.
2. On M5, observe the smaller structure and write the confirmation you would require.
3. Record what would invalidate the idea. If the H1 context is unclear or M5 does not confirm, stand aside.

## Analyse Gold and other relevant markets

Apply the same observation process to Gold and one other market relevant to your study. Compare what each chart shows; do not assume the markets behave identically or that an example represents live conditions.

## Apply your stated plan

Your plan specifies 2% risk per trade, a minimum planned risk-to-reward of 1:3, a maximum daily loss of 3%, and moving to breakeven at 1:1 according to the trade plan. These are your stated rules, not a guarantee or proof that a setup is valid.

## Review

- Which timeframe sets your higher-timeframe bias?
- What evidence do you still require on M5?
- What is your decision when confirmation is absent?

No forced entries, FOMO, or revenge trading. No setup means no trade.

**NO CONFIRMATION, NO ENTRY.**
$lesson$,
    updated_at = NOW()
WHERE lesson_key = 'multi-timeframe-context';

UPDATE member_learning_lessons
SET summary = 'Use your confirmation checklist and stated risk limits before deciding whether to stand aside or continue.',
    body_markdown = $lesson$
## Define confirmation before looking for an entry

Write down the evidence you need to observe on your M5 entry timeframe, and what would weaken or invalidate the idea. A BOS, CHoCH, order-block label, or gap is not confirmation by itself. First establish your H1 bias; do not force M5 evidence to agree with an unclear higher-timeframe view.

## Apply your established risk plan

- Risk **2% per trade**.
- Require a minimum planned risk-to-reward of **1:3**.
- Respect a maximum daily loss of **3%**.
- Move to breakeven at **1:1**, according to your trade plan.

These are your stated rules for study and planning. They do not establish that a setup is valid or guarantee an outcome.

## Practise and analyse

1. Use a hypothetical chart example; no live market data is implied.
2. Write the H1 bias, M5 confirmation, and invalidation condition.
3. Check the planned risk and reward against your rules before considering execution.
4. If the evidence is unclear, the plan is invalidated, or your daily limit is reached, stop and record the reason.

Apply the exercise to Gold and another relevant market you study. Do not force the same conclusion on both.

## Review before moving forward

- What confirmation is required by your plan?
- Does the hypothetical plan meet your risk and reward rules?
- Is there a valid setup, or is standing aside the correct choice?

No forced entries, FOMO, or revenge trading. No setup means no trade.

**NO CONFIRMATION, NO ENTRY.**
$lesson$,
    updated_at = NOW()
WHERE lesson_key = 'confirmation-and-risk-planning';

COMMIT;
