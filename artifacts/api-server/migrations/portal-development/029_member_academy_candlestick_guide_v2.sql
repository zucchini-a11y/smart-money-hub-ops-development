-- Full member Academy sequence based on the updated VAYDA candlestick guide.
-- Development-only: the live schema and production member progress are untouched.
BEGIN;
SET LOCAL search_path TO smh_test;

DO $$
BEGIN
    IF current_schema() <> 'smh_test' THEN
        RAISE EXCEPTION 'Academy guide update is Development-only (smh_test).';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM member_learning_lessons
        WHERE lesson_key NOT IN (
            'orientation',
            'candle-anatomy',
            'swing-high-low',
            'market-structure',
            'multi-timeframe-context',
            'bos-and-choch',
            'change-of-character',
            'mss-displacement',
            'liquidity-and-equal-highs-lows',
            'liquidity-sweep',
            'inducement',
            'fair-value-gaps',
            'inverse-fvg',
            'volume-imbalance-liquidity-void',
            'order-blocks-in-context',
            'breaker-block',
            'mitigation-block',
            'rejection-block',
            'premium-discount-ote',
            'power-of-three-judas-swing',
            'complete-smc-trade-model',
            'sessions-and-kill-zones',
            'confirmation-and-risk-planning'
        )
    ) THEN
        RAISE EXCEPTION 'Unexpected Academy lesson found; review before reordering the Development curriculum.';
    END IF;
END
$$;

-- Move the existing sequence out of the way before assigning the new positions.
-- Progress rows are keyed by lesson_key and are intentionally not changed.
UPDATE member_learning_lessons SET sequence = sequence + 1000;

INSERT INTO member_learning_lessons
    (lesson_key, title, summary, body_markdown, sequence, published, created_at, updated_at)
VALUES
(
    'orientation',
    'Our trading philosophy and how to study',
    'Follow Learn, Practise, Analyse, and Review using your stated H1/M5 and risk framework.',
$lesson$
Welcome to the VAYDA Smart Money Hub Trading Academy. Every module follows the same route: understand the concept, practise it on a chart, analyse Gold and another relevant market, then review what you learned.

## Our trading philosophy

- Higher-timeframe bias: **H1**.
- Entry timeframe: **M5**.
- Risk per trade: **2%**.
- Minimum planned risk-to-reward: **1:3**.
- Maximum daily loss: **3%**.
- Move to breakeven at **1:1**, according to your trade plan.
- No forced entries, FOMO, or revenge trading.
- No setup means no trade.

**NO CONFIRMATION, NO ENTRY.**

These are your stated plan values. They do not prove that a setup is valid or guarantee an outcome.
$lesson$, 1, TRUE, NOW(), NOW()
),
(
    'candle-anatomy',
    'How to read candles',
    'Read open, high, low, and close before labeling a candle pattern.',
$lesson$
A candlestick records four prices for one period: **open, high, low, and close**. The candle body shows the open-to-close range; the wicks show the high and low beyond the body. The guide uses green for a close above the open and red for a close below it. Always check the chart legend because colors can vary by platform.

The guide diagrams are schematic teaching examples, not market data. Read each candle first; add pattern labels only after you can describe what is visibly shown.

## Study check

1. Point out the open, high, low, and close on one candle.
2. Compare a candle's body with its wicks.
3. Describe whether it closed above or below its open without inferring what happens next.
$lesson$, 2, TRUE, NOW(), NOW()
),
(
    'swing-high-low',
    'Swing high and swing low',
    'Use neighboring candles to identify a visible local high or low.',
$lesson$
A swing high is a candle whose high is above the highs of nearby candles on both sides. A swing low is the mirror: its low is below the lows of nearby candles on both sides. The guide uses a three-candle minimum example; the timeframe and surrounding chart context still matter.

Mark only the swings that are meaningful at the timeframe you are studying. A small local turn is not automatically important to the larger structure.

## Keep in mind

The swing labels describe past candles. They do not predict a future break, reversal, or entry.
$lesson$, 3, TRUE, NOW(), NOW()
),
(
    'market-structure',
    'Market structure: HH, HL, LH, and LL',
    'Describe a sequence of swing highs and lows instead of relying on one candle.',
$lesson$
In common chart terminology, an uptrend is described by higher highs (HH) and higher lows (HL). A downtrend is described by lower highs (LH) and lower lows (LL). If the sequence is not clear, describe it as a range or unclear rather than forcing a direction.

A single wick does not establish a new trend. Compare meaningful swings and note whether a candle closes beyond a reference level.

## Study check

Label the visible swings first. Then explain which sequence supports your description and what evidence would change it.
$lesson$, 4, TRUE, NOW(), NOW()
),
(
    'multi-timeframe-context',
    'H1 bias and M5 entry context',
    'Use H1 to describe context and M5 to inspect the confirmation required by your plan.',
$lesson$
Your framework uses **H1** for higher-timeframe bias and **M5** for entry-timeframe review. On H1, describe visible structure as bullish, bearish, ranging, or unclear. On M5, record the evidence you would need and what would invalidate the idea.

The timeframe alone does not confirm a trade. If H1 is unclear or M5 does not show the planned confirmation, stand aside.

Apply the same observation process to Gold and one other relevant market. Do not assume the markets behave identically or that a study example represents live conditions.
$lesson$, 5, TRUE, NOW(), NOW()
),
(
    'bos-and-choch',
    'Break of Structure (BOS)',
    'Identify a close beyond a prior swing in the direction of the observed structure.',
$lesson$
A Break of Structure (BOS) is commonly described when a candle body closes beyond a recent swing in the direction of the existing structure. A wick that passes a level and closes back does not meet this close-based description.

Use BOS as a label for what the chart has done. It is not an entry by itself and does not guarantee continuation. Avoid chasing the break; return to your H1/M5 plan and define what further confirmation and risk controls apply.
$lesson$, 6, TRUE, NOW(), NOW()
),
(
    'change-of-character',
    'Change of Character (CHoCH)',
    'Study the first close that breaks against a previously observed swing sequence.',
$lesson$
A Change of Character (CHoCH) is commonly used for a close that breaks a relevant swing against the previously observed structure. It may be an early sign of a possible shift, but it does not prove that a reversal has occurred.

Compare the break with H1 context and the rest of the chart. Your plan still requires its own M5 confirmation; a CHoCH label alone is not an entry signal.
$lesson$, 7, TRUE, NOW(), NOW()
),
(
    'mss-displacement',
    'Market Structure Shift and displacement',
    'Describe a forceful structure break and the candle movement around it.',
$lesson$
Some SMC traders use Market Structure Shift (MSS) for a structure break accompanied by displacement: a forceful move with relatively large bodies and less candle overlap. A gap may appear in the sequence, depending on the chart and timeframe.

Terminology varies. Describe the candles you can see before deciding whether a label fits. Strong-looking candles do not guarantee follow-through or establish a valid setup.
$lesson$, 8, TRUE, NOW(), NOW()
),
(
    'liquidity-and-equal-highs-lows',
    'Liquidity and equal highs and lows',
    'Mark repeated swing levels as chart references without assuming hidden orders.',
$lesson$
In Smart Money Concepts, traders use “liquidity” when discussing places where orders may be concentrated. A chart does not show every resting order, so an equal-high or equal-low area is a visible reference—not proof of hidden stops.

Mark two or more visible swing highs or lows near a similar price. Observe whether price approaches, passes, rejects, or ignores the area. The pattern alone does not predict which outcome will happen.
$lesson$, 9, TRUE, NOW(), NOW()
),
(
    'liquidity-sweep',
    'Liquidity sweep',
    'Compare a wick through a reference level with a close beyond it.',
$lesson$
A liquidity sweep is commonly described when a wick passes a visible high or low and the candle closes back inside the prior range. A close beyond the level is described differently in close-based structure analysis.

This is a way to classify a chart observation, not proof of why price moved. A sweep does not guarantee a reversal and is not an entry signal without the confirmation and risk checks in your plan.
$lesson$, 10, TRUE, NOW(), NOW()
),
(
    'inducement',
    'Inducement',
    'Study the SMC label for a smaller swing before a larger chart reference.',
$lesson$
Some SMC frameworks call a small, obvious swing before a larger point of interest “inducement.” The term describes one interpretation of the chart; it does not establish that traders were trapped or reveal their orders.

Mark the smaller swing and observe whether price passes it before reaching another visible area. Treat this as a study filter, not a mandatory condition or standalone signal. The guide notes that it is not required in every model.
$lesson$, 11, TRUE, NOW(), NOW()
),
(
    'fair-value-gaps',
    'Fair Value Gap (FVG)',
    'Identify the common three-candle gap definition and its limits.',
$lesson$
In one common SMC convention, a bullish Fair Value Gap (FVG) is the space between candle one's high and candle three's low when candle three's low is above candle one's high. The bearish example reverses that relationship. The middle candle is often the strongest in the sequence.

Mark the first, middle, and third candles before drawing a zone. A chart gap is not proof that no transactions occurred there, and price is not required to revisit it.
$lesson$, 12, TRUE, NOW(), NOW()
),
(
    'inverse-fvg',
    'Inverse Fair Value Gap (IFVG)',
    'Study how some traders relabel a gap after a close through it.',
$lesson$
An Inverse Fair Value Gap is commonly described when price closes through an FVG against its original direction and the zone is then viewed from the opposite side. A wick through the area alone is not the close-based condition used in the guide.

Terminology and chart construction vary. A failed gap does not guarantee a reaction on a later revisit and is not a trade signal by itself.
$lesson$, 13, TRUE, NOW(), NOW()
),
(
    'volume-imbalance-liquidity-void',
    'Volume imbalance and liquidity void',
    'Distinguish a body gap with overlapping wicks from a run of directional candles.',
$lesson$
In the guide's convention, a volume imbalance is a gap between the bodies of consecutive candles while their wicks overlap. A liquidity void describes a run of strong one-directional candles with little overlap, sometimes containing several chart gaps.

These are chart-pattern labels, not direct measurements of all market transactions or available liquidity. Treat them as secondary observations and compare them with your broader H1/M5 plan.
$lesson$, 14, TRUE, NOW(), NOW()
),
(
    'order-blocks-in-context',
    'Order Block (OB)',
    'Study the SMC zone label around a candle before a structure break.',
$lesson$
Some SMC frameworks label the last opposite-direction candle before a move that displaces price and breaks structure as an Order Block (OB). The marked zone may use the candle's full range or body depending on the trader's convention.

A candlestick chart cannot establish who placed orders or what caused a move. Compare the candidate area with visible structure and record what would make the label less relevant. An OB is not a guaranteed support or resistance zone and is not an entry signal.
$lesson$, 15, TRUE, NOW(), NOW()
),
(
    'breaker-block',
    'Breaker Block',
    'Compare a failed OB zone with its later use as an opposite-side reference.',
$lesson$
A Breaker Block is described in some SMC frameworks when a marked Order Block fails, price closes through it, and the old zone is viewed from the opposite direction. The guide distinguishes a breaker from a mitigation block by whether a liquidity sweep preceded the flip.

These are framework-specific labels. A close through a zone does not guarantee that a later revisit will hold or reverse.
$lesson$, 16, TRUE, NOW(), NOW()
),
(
    'mitigation-block',
    'Mitigation Block',
    'Study a failed swing and the zone traders may mark around it.',
$lesson$
The guide describes a mitigation block around a failed attempt to take a prior high or low, followed by a break in the other direction. The last candle area near the failed swing may be marked as a reference zone.

Definitions vary between SMC frameworks. The label does not prove that positions were “mitigated,” and it should not be used as a standalone signal. Compare examples with breakers and record the visible differences.
$lesson$, 17, TRUE, NOW(), NOW()
),
(
    'rejection-block',
    'Rejection Block',
    'Mark a prominent wick area at a swing as a chart reference.',
$lesson$
A Rejection Block is commonly described as a prominent candle wick area near a swing high or swing low. The guide marks the space from the wick tip toward the candle body; the exact boundary varies by convention.

Compare the wick with nearby candles and the larger chart context. Ordinary small wicks are not automatically meaningful, and a marked wick area does not guarantee a later reaction.
$lesson$, 18, TRUE, NOW(), NOW()
),
(
    'premium-discount-ote',
    'Premium, discount, equilibrium, and OTE',
    'Measure locations within a selected dealing range without treating them as a trade direction.',
$lesson$
Some SMC traders define a dealing range between a selected swing low and swing high. Its midpoint is called equilibrium (50%); areas above and below are called premium and discount. The guide's Optimal Trade Entry (OTE) example uses a 62%–79% retracement band, with 70.5% often marked.

These labels depend on which swings a trader selects and do not determine a buy or sell by themselves. The uploaded guide presents them as a context framework; your stated H1/M5 confirmation, risk, and 1:3 rules remain separate checks.
$lesson$, 19, TRUE, NOW(), NOW()
),
(
    'power-of-three-judas-swing',
    'Power of Three (AMD) and Judas Swing',
    'Study accumulation, a possible false move, and later expansion as an SMC framework.',
$lesson$
Power of Three (AMD) labels three phases: accumulation, manipulation, and distribution. A Judas Swing is a term some traders use for a move that first passes one side of a range before moving the other way.

The guide uses the Asia range and later session activity as a study example. This pattern does not occur every day, and a session label cannot confirm direction or guarantee a setup. Record what the chart shows rather than expecting the sequence.
$lesson$, 20, TRUE, NOW(), NOW()
),
(
    'complete-smc-trade-model',
    'The Complete SMC Trade Model',
    'Review the guide’s schematic sequence against your stated confirmation and risk plan.',
$lesson$
The updated guide's bullish schematic combines a higher-timeframe view, visible equal lows, a sweep, a possible CHoCH/MSS with displacement, a chart gap, and a later retrace. Its illustration labels a planned 1R risk and 3R target, then shows breakeven at 1:1.

Use this as a checklist for studying a hypothetical or historical chart—not as a signal. Your plan requires H1 context, M5 confirmation, 2% risk per trade, at least 1:3 planned risk-to-reward, a 3% maximum daily loss, and breakeven at 1:1 according to your trade plan. If a required condition is absent, no setup means no trade.
$lesson$, 21, TRUE, NOW(), NOW()
),
(
    'sessions-and-kill-zones',
    'Sessions, kill zones, and extra terms',
    'Use the guide’s New York-time study windows carefully and check daylight saving and broker time.',
$lesson$
The guide lists commonly discussed windows in **New York time**: Asian range 8:00 PM–12:00 AM, London kill zone 2:00 AM–5:00 AM, New York kill zone 7:00 AM–10:00 AM, and London close 10:00 AM–12:00 PM. These are study references, not guaranteed high-activity periods. Convert carefully for daylight saving and confirm your broker's chart timezone before comparing candles.

Other terms in the guide include displacement (a strong one-directional move), POI (point of interest), mitigation/unmitigated, consequent encroachment (a 50% midpoint), internal/external structure, dealing range, PDH/PDL, SMT divergence, propulsion block, HTF/LTF, and Turtle Soup. Definitions differ among traders; use the lesson glossary as terminology, not proof of market behavior.
$lesson$, 22, TRUE, NOW(), NOW()
),
(
    'confirmation-and-risk-planning',
    'Pre-trade checklist and risk note',
    'Use the ten checks to identify missing evidence and when the planned decision is to stand aside.',
$lesson$
Use this checklist as a review of **your stated framework**, not as a recommendation to place a trade:

1. **H1 bias:** Describe the visible structure and nearby highs, lows, and reference areas.
2. **Location:** Record where price sits within the selected H1 range; this is context, not confirmation.
3. **Sweep:** Note whether the chart shows the sweep pattern described in the guide.
4. **M5 confirmation:** Check the evidence required by your plan. **NO CONFIRMATION, NO ENTRY.**
5. **Entry area:** Record the zone you are studying. Do not chase price.
6. **Stop and size:** Calculate the hypothetical position so the planned risk stays within **2%**.
7. **1:3 gate:** If the planned target does not allow at least **1:3**, skip the setup.
8. **Management:** Move to breakeven at **1:1** only as specified in your plan.
9. **Daily limit:** Stop at the **3%** maximum daily loss; do not revenge trade.
10. **Review:** Save a screenshot and journal the observation, whether hypothetical or completed.

The diagrams are schematic teaching examples, not real market data. No pattern is guaranteed to work. Leveraged trading carries a high risk of loss. This lesson is educational, not financial advice.
$lesson$, 23, TRUE, NOW(), NOW()
)
ON CONFLICT (lesson_key) DO UPDATE SET
    title = EXCLUDED.title,
    summary = EXCLUDED.summary,
    body_markdown = EXCLUDED.body_markdown,
    sequence = EXCLUDED.sequence,
    published = EXCLUDED.published,
    updated_at = NOW();

COMMIT;
