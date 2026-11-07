import type { ReactNode } from 'react';

function DiagramFrame({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="ml-diagram-panel" aria-label={`${title} diagram explanation`}>
      <div className="ml-diagram-heading">
        <div>
          <span className="ml-eyebrow">VISUAL EXPLANATION</span>
          <h3>{title}</h3>
        </div>
        <span className="ml-diagram-note">ILLUSTRATIVE · NOT LIVE DATA</span>
      </div>
      {children}
      <p className="ml-diagram-description">{description}</p>
      <p className="ml-diagram-disclaimer">For education only. This diagram is not an entry signal or financial advice.</p>
    </section>
  );
}

function OrientationDiagram() {
  return (
    <div className="ml-diagram-canvas">
      <svg viewBox="0 0 720 160" role="img" aria-labelledby="ml-orientation-title ml-orientation-desc">
        <title id="ml-orientation-title">A deliberate study sequence</title>
        <desc id="ml-orientation-desc">Four steps: observe price, map structure, wait for confirmation, and define risk.</desc>
        <defs>
          <linearGradient id="ml-orientation-line" x1="0" x2="1">
            <stop stopColor="#a894ff" />
            <stop offset="1" stopColor="#5bd8e7" />
          </linearGradient>
        </defs>
        <line x1="85" y1="78" x2="635" y2="78" stroke="url(#ml-orientation-line)" strokeWidth="2" opacity=".8" />
        {[
          { x: 20, number: '01', label: 'Observe price' },
          { x: 198, number: '02', label: 'Map structure' },
          { x: 376, number: '03', label: 'Wait for confirmation' },
          { x: 554, number: '04', label: 'Define risk' },
        ].map((step) => (
          <g key={step.number}>
            <rect x={step.x} y="43" width="146" height="70" rx="14" fill="#111a2d" stroke="rgba(154,173,214,.28)" />
            <text x={step.x + 15} y="64" fill="#9f8aff" fontSize="10" fontFamily="monospace" letterSpacing="1">{step.number}</text>
            <text x={step.x + 15} y="88" fill="#eef2ff" fontSize="12" fontFamily="sans-serif" fontWeight="600">{step.label}</text>
            <circle cx={step.x + 131} cy="78" r="4" fill="#63dce8" />
          </g>
        ))}
      </svg>
    </div>
  );
}

type Candle = { x: number; open: number; high: number; low: number; close: number };
type CandleMark = { x: number; price: number; label: string; placement: 'above' | 'below' };

function CandlestickChart({
  id,
  title,
  description,
  candles,
  width = 720,
  height = 230,
  level,
  zone,
  marks = [],
}: {
  id: string;
  title: string;
  description: string;
  candles: Candle[];
  width?: number;
  height?: number;
  level?: { price: number; label: string };
  zone?: { high: number; low: number; label: string; xStart?: number; xEnd?: number };
  marks?: CandleMark[];
}) {
  const top = height * 0.14;
  const bottom = height * 0.88;
  const left = width * 0.055;
  const right = width * 0.96;
  const y = (price: number) => bottom - (price / 100) * (bottom - top);
  const bodyWidth = width < 400 ? 13 : 22;

  return (
    <div className="ml-diagram-canvas">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`${id}-title ${id}-desc`}>
        <title id={`${id}-title`}>{title}</title>
        <desc id={`${id}-desc`}>{description}</desc>
        {[20, 45, 70].map((price) => (
          <line key={price} x1={left} x2={right} y1={y(price)} y2={y(price)} stroke="rgba(154,173,214,.13)" />
        ))}
        {zone && (
          <>
            <rect
              x={zone.xStart ?? left}
              y={y(zone.high)}
              width={(zone.xEnd ?? right) - (zone.xStart ?? left)}
              height={Math.max(3, y(zone.low) - y(zone.high))}
              fill="rgba(91,216,231,.09)"
              stroke="rgba(91,216,231,.5)"
              strokeDasharray="4 4"
            />
            <text
              x={(zone.xEnd ?? right) - 3}
              y={y(zone.high) - 4}
              textAnchor="end"
              fill="#8ee8ef"
              fontSize={width < 400 ? 7 : 9}
              fontFamily="monospace"
            >
              {zone.label}
            </text>
          </>
        )}
        {level && (
          <>
            <line x1={left} x2={right} y1={y(level.price)} y2={y(level.price)} stroke="#63dce8" strokeWidth="1.3" strokeDasharray="5 5" />
            <text x={right - 2} y={y(level.price) - 5} textAnchor="end" fill="#8ee8ef" fontSize={width < 400 ? 7 : 9} fontFamily="monospace">{level.label}</text>
          </>
        )}
        {candles.map((candle, index) => {
          const color = candle.close >= candle.open ? '#54d6bf' : '#ef788a';
          const bodyY = Math.min(y(candle.open), y(candle.close));
          const bodyHeight = Math.max(3, Math.abs(y(candle.open) - y(candle.close)));
          return (
            <g key={`${candle.x}-${index}`} aria-label={candle.close >= candle.open ? 'Bullish candlestick' : 'Bearish candlestick'}>
              <line x1={candle.x} x2={candle.x} y1={y(candle.high)} y2={y(candle.low)} stroke={color} strokeWidth="2" />
              <rect x={candle.x - bodyWidth / 2} y={bodyY} width={bodyWidth} height={bodyHeight} rx="1.5" fill={color} />
            </g>
          );
        })}
        {marks.map((mark) => (
          <text
            key={`${mark.x}-${mark.label}`}
            x={mark.x}
            y={y(mark.price) + (mark.placement === 'above' ? -8 : 15)}
            textAnchor="middle"
            fill="#dce6ff"
            fontSize={width < 400 ? 8 : 10}
            fontFamily="monospace"
          >
            {mark.label}
          </text>
        ))}
      </svg>
    </div>
  );
}

function MarketStructureDiagram() {
  const candles: Candle[] = [
    { x: 52, open: 30, close: 42, high: 47, low: 22 },
    { x: 120, open: 42, close: 38, high: 51, low: 34 },
    { x: 188, open: 38, close: 56, high: 62, low: 35 },
    { x: 256, open: 56, close: 48, high: 59, low: 43 },
    { x: 324, open: 48, close: 67, high: 73, low: 45 },
    { x: 392, open: 67, close: 60, high: 70, low: 54 },
    { x: 460, open: 60, close: 80, high: 86, low: 58 },
    { x: 528, open: 80, close: 71, high: 83, low: 65 },
    { x: 596, open: 71, close: 89, high: 94, low: 68 },
    { x: 664, open: 89, close: 81, high: 91, low: 75 },
  ];
  return (
    <CandlestickChart
      id="ml-structure"
      title="Illustrative candlestick sequence with higher highs and higher lows"
      description="Ten schematic candlesticks show rising swing highs and rising swing lows. Candle bodies show open and close; wicks show the high and low."
      candles={candles}
      marks={[
        { x: 324, price: 73, label: 'HH', placement: 'above' },
        { x: 392, price: 54, label: 'HL', placement: 'below' },
        { x: 460, price: 86, label: 'HH', placement: 'above' },
        { x: 528, price: 65, label: 'HL', placement: 'below' },
      ]}
    />
  );
}

function LiquidityReferenceDiagram() {
  const candles: Candle[] = [
    { x: 52, open: 25, close: 38, high: 46, low: 19 },
    { x: 114, open: 38, close: 55, high: 66, low: 34 },
    { x: 176, open: 55, close: 50, high: 82, low: 45 },
    { x: 238, open: 50, close: 58, high: 65, low: 43 },
    { x: 300, open: 58, close: 67, high: 82, low: 54 },
    { x: 362, open: 67, close: 60, high: 76, low: 54 },
    { x: 424, open: 60, close: 48, high: 72, low: 44 },
    { x: 486, open: 48, close: 62, high: 68, low: 41 },
    { x: 548, open: 62, close: 70, high: 77, low: 58 },
    { x: 610, open: 70, close: 66, high: 82, low: 60 },
    { x: 672, open: 66, close: 73, high: 79, low: 62 },
  ];
  return (
    <CandlestickChart
      id="ml-liquidity"
      title="Candlestick example of repeated swing highs"
      description="The wick highs approach a similar horizontal area. Candles are schematic OHLC examples; they show visible price, not hidden orders."
      candles={candles}
      zone={{ high: 84, low: 80, label: 'EQUAL-HIGH REFERENCE ZONE' }}
    />
  );
}

function StructureBreakDiagram({ kind }: { kind: 'bos' | 'choch' }) {
  const isBos = kind === 'bos';
  const candles: Candle[] = isBos
    ? [
        { x: 28, open: 22, close: 35, high: 44, low: 18 },
        { x: 72, open: 35, close: 48, high: 55, low: 31 },
        { x: 116, open: 48, close: 43, high: 60, low: 38 },
        { x: 160, open: 43, close: 57, high: 65, low: 40 },
        { x: 204, open: 57, close: 53, high: 62, low: 49 },
        { x: 248, open: 53, close: 72, high: 78, low: 51 },
        { x: 292, open: 72, close: 68, high: 80, low: 63 },
      ]
    : [
        { x: 28, open: 22, close: 35, high: 43, low: 18 },
        { x: 72, open: 35, close: 48, high: 55, low: 31 },
        { x: 116, open: 48, close: 42, high: 60, low: 38 },
        { x: 160, open: 42, close: 60, high: 68, low: 40 },
        { x: 204, open: 60, close: 54, high: 64, low: 49 },
        { x: 248, open: 54, close: 68, high: 73, low: 51 },
        { x: 292, open: 68, close: 44, high: 70, low: 38 },
      ];
  return (
    <figure className="ml-comparison-card">
      <figcaption>{isBos ? 'BOS · break with structure' : 'CHoCH · possible character shift'}</figcaption>
      <CandlestickChart
        id={isBos ? 'ml-bos' : 'ml-choch'}
        title={isBos ? 'Candlestick example of a break of structure' : 'Candlestick example of a possible change of character'}
        description={isBos
          ? 'Schematic candles close beyond a prior swing high, illustrating a break with the existing structure.'
          : 'Schematic candles close below a prior higher low, illustrating a possible break against the prior swing sequence.'}
        candles={candles}
        width={340}
        height={170}
        level={isBos ? { price: 65, label: 'PRIOR HIGH' } : { price: 49, label: 'PRIOR HIGHER LOW' }}
      />
      <p>{isBos
        ? 'A break beyond a prior swing in the existing direction is described as BOS.'
        : 'A break against the prior swing sequence may suggest a shift. It still needs context and confirmation.'}</p>
    </figure>
  );
}

function OrderBlockDiagram() {
  const candles: Candle[] = [
    { x: 52, open: 25, close: 37, high: 43, low: 20 },
    { x: 114, open: 37, close: 48, high: 54, low: 33 },
    { x: 176, open: 48, close: 42, high: 59, low: 38 },
    { x: 238, open: 42, close: 38, high: 49, low: 34 },
    { x: 300, open: 38, close: 61, high: 68, low: 36 },
    { x: 362, open: 61, close: 76, high: 82, low: 57 },
    { x: 424, open: 76, close: 70, high: 80, low: 66 },
    { x: 486, open: 70, close: 87, high: 93, low: 68 },
    { x: 548, open: 87, close: 81, high: 91, low: 76 },
    { x: 610, open: 81, close: 91, high: 96, low: 78 },
  ];
  return (
    <CandlestickChart
      id="ml-order-block"
      title="Candlestick example with a highlighted candidate area"
      description="A small bearish candle is highlighted before larger bullish candles. Some SMC frameworks label such an area; the chart does not prove who placed orders or why price moved."
      candles={candles}
      zone={{ high: 50, low: 34, label: 'CANDIDATE AREA', xStart: 218, xEnd: 258 }}
    />
  );
}

function FairValueGapDiagram() {
  const candles: Candle[] = [
    { x: 52, open: 38, close: 47, high: 55, low: 34 },
    { x: 114, open: 47, close: 75, high: 81, low: 43 },
    { x: 176, open: 75, close: 80, high: 88, low: 68 },
    { x: 238, open: 80, close: 71, high: 84, low: 67 },
    { x: 300, open: 71, close: 73, high: 78, low: 65 },
    { x: 362, open: 73, close: 62, high: 76, low: 57 },
    { x: 424, open: 62, close: 68, high: 72, low: 59 },
    { x: 486, open: 68, close: 75, high: 80, low: 65 },
    { x: 548, open: 75, close: 67, high: 78, low: 61 },
    { x: 610, open: 67, close: 72, high: 77, low: 64 },
  ];
  return (
    <CandlestickChart
      id="ml-fair-value-gap"
      title="Three-candle imbalance example"
      description="In this schematic bullish example, candle three's low is above candle one's high. The highlighted space is the commonly used three-candle gap definition."
      candles={candles}
      zone={{ high: 68, low: 55, label: 'ILLUSTRATIVE GAP', xStart: 37, xEnd: 194 }}
    />
  );
}

function MultiTimeframeDiagram() {
  const widerCandles: Candle[] = [
    { x: 28, open: 28, close: 40, high: 47, low: 22 },
    { x: 72, open: 40, close: 34, high: 49, low: 30 },
    { x: 116, open: 34, close: 55, high: 62, low: 31 },
    { x: 160, open: 55, close: 49, high: 60, low: 44 },
    { x: 204, open: 49, close: 68, high: 76, low: 46 },
    { x: 248, open: 68, close: 60, high: 72, low: 55 },
    { x: 292, open: 60, close: 77, high: 84, low: 57 },
  ];
  const closerCandles: Candle[] = [
    { x: 28, open: 46, close: 52, high: 58, low: 42 },
    { x: 72, open: 52, close: 48, high: 56, low: 45 },
    { x: 116, open: 48, close: 61, high: 67, low: 46 },
    { x: 160, open: 61, close: 56, high: 64, low: 52 },
    { x: 204, open: 56, close: 65, high: 71, low: 54 },
    { x: 248, open: 65, close: 60, high: 69, low: 57 },
    { x: 292, open: 60, close: 70, high: 76, low: 58 },
  ];
  return (
    <div className="ml-comparison-diagrams">
      <figure className="ml-comparison-card">
        <figcaption>Wider context · larger swings</figcaption>
        <CandlestickChart
          id="ml-timeframe-wide"
          title="Schematic wider timeframe candles"
          description="A simplified candle sequence used to view broader swings."
          candles={widerCandles}
          width={340}
          height={170}
        />
      </figure>
      <figure className="ml-comparison-card">
        <figcaption>Closer detail · smaller movements</figcaption>
        <CandlestickChart
          id="ml-timeframe-close"
          title="Schematic closer timeframe candles"
          description="A simplified candle sequence showing more local detail without prescribing a specific timeframe."
          candles={closerCandles}
          width={340}
          height={170}
        />
      </figure>
    </div>
  );
}

function ConfirmationDiagram() {
  const movesAway: Candle[] = [
    { x: 28, open: 64, close: 58, high: 69, low: 54 },
    { x: 72, open: 58, close: 51, high: 61, low: 47 },
    { x: 116, open: 51, close: 55, high: 59, low: 48 },
    { x: 160, open: 55, close: 47, high: 57, low: 42 },
    { x: 204, open: 47, close: 38, high: 51, low: 34 },
    { x: 248, open: 38, close: 43, high: 47, low: 35 },
    { x: 292, open: 43, close: 30, high: 46, low: 25 },
  ];
  const movesThrough: Candle[] = [
    { x: 28, open: 64, close: 58, high: 69, low: 54 },
    { x: 72, open: 58, close: 51, high: 61, low: 47 },
    { x: 116, open: 51, close: 55, high: 59, low: 48 },
    { x: 160, open: 55, close: 58, high: 62, low: 52 },
    { x: 204, open: 58, close: 65, high: 71, low: 56 },
    { x: 248, open: 65, close: 74, high: 80, low: 62 },
    { x: 292, open: 74, close: 68, high: 78, low: 65 },
  ];
  return (
    <div className="ml-comparison-diagrams">
      <figure className="ml-comparison-card">
        <figcaption>One possible observation · price moves away</figcaption>
        <CandlestickChart
          id="ml-confirmation-away"
          title="Schematic candles moving away from a reference area"
          description="One hypothetical candlestick sequence after approaching a reference area."
          candles={movesAway}
          width={340}
          height={170}
          level={{ price: 55, label: 'REFERENCE AREA' }}
        />
      </figure>
      <figure className="ml-comparison-card">
        <figcaption>Another possible observation · price moves through</figcaption>
        <CandlestickChart
          id="ml-confirmation-through"
          title="Schematic candles moving through a reference area"
          description="A second hypothetical candlestick sequence showing a different possible outcome."
          candles={movesThrough}
          width={340}
          height={170}
          level={{ price: 55, label: 'REFERENCE AREA' }}
        />
      </figure>
    </div>
  );
}

export function MemberLessonDiagram({ lessonId }: { lessonId: string }) {
  if (lessonId === 'orientation') {
    return (
      <DiagramFrame
        title="A calm study sequence"
        description="Use the steps as a learning routine: observe first, describe what price has done, then consider confirmation and risk."
      >
        <OrientationDiagram />
      </DiagramFrame>
    );
  }

  if (lessonId === 'market-structure') {
    return (
      <DiagramFrame
        title="Reading a sequence of swings"
        description="This simplified rising sequence shows higher highs and higher lows. Structure describes observed swings; it does not predict the next move."
      >
        <MarketStructureDiagram />
      </DiagramFrame>
    );
  }

  if (lessonId === 'liquidity-and-equal-highs-lows') {
    return (
      <DiagramFrame
        title="Equal highs are visible references"
        description="Repeated swing highs can be marked as a reference zone. The chart does not confirm hidden stop orders, and price may react in different ways."
      >
        <LiquidityReferenceDiagram />
      </DiagramFrame>
    );
  }

  if (lessonId === 'bos-and-choch') {
    return (
      <DiagramFrame
        title="Two ways structure can break"
        description="BOS and CHoCH are descriptions of price structure. Neither one alone confirms a trade or guarantees what happens next."
      >
        <div className="ml-comparison-diagrams">
          <StructureBreakDiagram kind="bos" />
          <StructureBreakDiagram kind="choch" />
        </div>
      </DiagramFrame>
    );
  }

  if (lessonId === 'order-blocks-in-context') {
    return (
      <DiagramFrame
        title="A candidate candle area, not proof of orders"
        description="Some frameworks highlight the candle before a sharp move. The chart shows only candle data; the label does not establish who traded or what caused the move."
      >
        <OrderBlockDiagram />
      </DiagramFrame>
    );
  }

  if (lessonId === 'fair-value-gaps') {
    return (
      <DiagramFrame
        title="A three-candle gap convention"
        description="The highlighted area shows the gap between candle one's high and candle three's low in one schematic bullish example. Price is not required to revisit it."
      >
        <FairValueGapDiagram />
      </DiagramFrame>
    );
  }

  if (lessonId === 'multi-timeframe-context') {
    return (
      <DiagramFrame
        title="Context and detail are different views"
        description="These are schematic views, not fixed timeframe instructions. Smaller candles add detail but do not guarantee more certainty."
      >
        <MultiTimeframeDiagram />
      </DiagramFrame>
    );
  }

  if (lessonId === 'confirmation-and-risk-planning') {
    return (
      <DiagramFrame
        title="A reference area can have different outcomes"
        description="Candles may move away from an area or continue through it. These examples show why a level or pattern alone is not confirmation."
      >
        <ConfirmationDiagram />
      </DiagramFrame>
    );
  }

  return null;
}
