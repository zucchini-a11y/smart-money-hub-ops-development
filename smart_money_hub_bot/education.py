"""Short, editable SMC learning cards shown by the Learn menu."""

EDUCATION: dict[str, tuple[str, str]] = {
    "structure": (
        "Market structure",
        "Read meaningful swing highs and lows in context. A bullish sequence of higher highs and higher lows suggests upward structure; lower highs and lower lows suggest downward structure. One candle alone does not define the trend.",
    ),
    "bos_choch": (
        "BOS and CHoCH",
        "A Break of Structure (BOS) is a decisive break of a relevant swing in the direction of the existing structure. A Change of Character (CHoCH) is an early sign the prior structure may be shifting. Neither is an entry by itself: wait for confirmation and a retest.",
    ),
    "liquidity": (
        "Liquidity",
        "Obvious highs and lows can attract stop orders. Buy-side liquidity (BSL) is commonly above highs; sell-side liquidity (SSL) is commonly below lows. A sweep provides context, not a guaranteed reversal.",
    ),
    "order_blocks": (
        "Order Blocks",
        "A commonly watched order block is the last opposing candle before a displacement that breaks relevant structure. It is a possible point of interest only when there is a valid reason and the broader context supports it.",
    ),
    "fvg": (
        "FVG and IFVG",
        "A Fair Value Gap (FVG) is a price imbalance, often marked across the first and third candles of a three-candle move. If price decisively breaks through a gap, some traders watch it as an Inverse FVG (IFVG). Neither is an automatic entry signal.",
    ),
    "poi": (
        "Points of Interest",
        "A POI needs a reason: structural relevance, context, and a relationship to liquidity or displacement. Do not enter only because price touched a box or a candle has a familiar label.",
    ),
    "confirmation": (
        "Confirmation",
        "Confirmation is evidence your setup is behaving as planned, such as a response after a liquidity event and a structural shift. Require the confirmation specified by your chosen entry model; a setup label does not guarantee an outcome.",
    ),
    "retest": (
        "Retests",
        "In a retest-based model, wait for price to return to the level or POI and show the planned response. A retest is not required by every entry model. If your model's setup is missed, do not chase it.",
    ),
    "risk": (
        "Risk management",
        "Decide the invalidation point, stop, and acceptable risk before entry. If the setup is missed or the risk no longer fits your plan, skip it. Protecting capital comes before chasing profit.",
    ),
    "psychology": (
        "Trading psychology",
        "Use a written plan, accept that missed setups are part of trading, and review decisions without shame. A disciplined no-trade decision can be better than an impulsive entry.",
    ),
}