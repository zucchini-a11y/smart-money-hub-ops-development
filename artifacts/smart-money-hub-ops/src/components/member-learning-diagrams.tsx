type GuideFigure = {
  id: string;
  title: string;
  alt: string;
  page: number;
};

const basePath = import.meta.env.BASE_URL.replace(/\/$/, "");
const apiBase = `${basePath}/api`;

const guideFigures: Record<string, GuideFigure[]> = {
  "candle-anatomy": [
    { id: "candle-anatomy", title: "How to read a candle", alt: "Green and red candlesticks illustrating open, high, low, and close.", page: 3 },
  ],
  "swing-high-low": [
    { id: "swing-high-low", title: "Swing highs and swing lows", alt: "Candlestick swing-high and swing-low examples.", page: 4 },
  ],
  "market-structure": [
    { id: "market-structure", title: "Market structure", alt: "Candlestick sequences illustrating higher highs, higher lows, lower highs, and lower lows.", page: 5 },
  ],
  "bos-and-choch": [
    { id: "bos", title: "Break of Structure", alt: "Bullish and bearish candlestick examples of a body closing beyond a swing level.", page: 6 },
  ],
  "change-of-character": [
    { id: "choch", title: "Change of Character", alt: "Candlestick example of a close through a prior swing against the previous structure.", page: 7 },
  ],
  "mss-displacement": [
    { id: "mss-displacement", title: "Market Structure Shift and displacement", alt: "Candles showing a forceful structure break and displacement.", page: 8 },
  ],
  "liquidity-and-equal-highs-lows": [
    { id: "liquidity-equal-highs-lows", title: "Equal highs and equal lows", alt: "Candlesticks with equal-high and equal-low reference levels.", page: 9 },
  ],
  "liquidity-sweep": [
    { id: "liquidity-sweep", title: "Liquidity sweep", alt: "A candle wick moves beyond a reference level and closes back inside.", page: 10 },
  ],
  inducement: [
    { id: "inducement", title: "Inducement", alt: "Candlestick example labeling a smaller swing and a later move to a reference area.", page: 11 },
  ],
  "fair-value-gaps": [
    { id: "fair-value-gap", title: "Fair Value Gap", alt: "Bullish and bearish three-candle Fair Value Gap examples.", page: 12 },
  ],
  "inverse-fvg": [
    { id: "inverse-fvg", title: "Inverse Fair Value Gap", alt: "Candlestick example of a gap failing and being viewed from the opposite direction.", page: 13 },
  ],
  "volume-imbalance-liquidity-void": [
    { id: "volume-imbalance-liquidity-void", title: "Volume imbalance and liquidity void", alt: "Candlestick examples comparing body imbalance and a run of directional candles.", page: 14 },
  ],
  "order-blocks-in-context": [
    { id: "order-block", title: "Order Block", alt: "Bullish and bearish candlestick zones labeled as order-block examples.", page: 15 },
  ],
  "breaker-block": [
    { id: "breaker-block", title: "Breaker Block", alt: "Candlestick illustration of a failed block and a later retest.", page: 16 },
  ],
  "mitigation-block": [
    { id: "mitigation-block", title: "Mitigation Block", alt: "Candlestick example of a failed swing and return to a marked zone.", page: 17 },
  ],
  "rejection-block": [
    { id: "rejection-block", title: "Rejection Block", alt: "Candlestick wicks marking example rejection areas.", page: 18 },
  ],
  "premium-discount-ote": [
    { id: "premium-discount-ote", title: "Premium, discount, and OTE", alt: "Candlestick range with midpoint and retracement reference zones.", page: 19 },
  ],
  "power-of-three-judas-swing": [
    { id: "power-of-three-judas-swing", title: "Power of Three and Judas Swing", alt: "Candlestick example organized into accumulation, a possible false move, and later expansion.", page: 20 },
  ],
  "multi-timeframe-context": [
    { id: "premium-discount-ote", title: "H1 range and location", alt: "Candlestick range with midpoint and retracement reference zones.", page: 19 },
    { id: "complete-smc-model", title: "H1 context with M5 confirmation", alt: "Schematic candlestick sequence combining higher-timeframe context with entry-timeframe confirmation.", page: 21 },
  ],
  "complete-smc-trade-model": [
    { id: "complete-smc-model", title: "Complete SMC model example", alt: "Candlestick diagram showing a schematic liquidity sweep, structure shift, entry area, a 1R risk and 3R target, and breakeven at 1:1.", page: 21 },
  ],
  "confirmation-and-risk-planning": [
    { id: "complete-smc-model", title: "The guide’s complete model", alt: "Schematic candlestick sequence showing a sweep, structure shift, entry area, 1R risk, 3R target, and breakeven at 1:1.", page: 21 },
  ],
};

function GuideFigureGallery({ lessonId, figures }: { lessonId: string; figures: GuideFigure[] }) {
  return (
    <div className="ml-guide-figure-gallery">
      {figures.map((figure) => (
        <figure className="ml-guide-figure" key={`${figure.id}-${figure.page}`}>
          <img
            src={`${apiBase}/member/learning/${encodeURIComponent(lessonId)}/figures/${encodeURIComponent(figure.id)}`}
            alt={figure.alt}
            loading="lazy"
            decoding="async"
          />
          <figcaption>
            <span><strong>{figure.title}</strong><small>Visual guide · page {figure.page}</small></span>
          </figcaption>
        </figure>
      ))}
      <p className="ml-guide-source-note">
        Diagrams from the updated SMC Candlestick Visual Guide. They are schematic illustrations, not live market data or trade signals.
      </p>
    </div>
  );
}

export function MemberLessonDiagram({ lessonId }: { lessonId: string }) {
  const figures = guideFigures[lessonId];
  if (!figures?.length) return null;
  return <GuideFigureGallery lessonId={lessonId} figures={figures} />;
}
