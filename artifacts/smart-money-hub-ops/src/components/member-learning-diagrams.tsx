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

function MarketStructureDiagram() {
  return (
    <div className="ml-diagram-canvas">
      <svg viewBox="0 0 720 230" role="img" aria-labelledby="ml-structure-title ml-structure-desc">
        <title id="ml-structure-title">Illustrative rising swing sequence</title>
        <desc id="ml-structure-desc">A simplified price path with higher highs and higher lows, used to describe one possible market structure.</desc>
        <defs>
          <linearGradient id="ml-structure-line" x1="0" x2="1">
            <stop stopColor="#a894ff" />
            <stop offset="1" stopColor="#5bd8e7" />
          </linearGradient>
        </defs>
        <path d="M42 190H680M42 145H680M42 100H680M42 55H680" stroke="rgba(154,173,214,.12)" />
        <path d="M54 186 L137 131 L204 160 L286 94 L359 126 L451 60 L523 96 L626 34" fill="none" stroke="url(#ml-structure-line)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        {[
          { x: 137, y: 131, text: 'Swing high' },
          { x: 204, y: 160, text: 'Higher low' },
          { x: 286, y: 94, text: 'Higher high' },
          { x: 359, y: 126, text: 'Higher low' },
          { x: 451, y: 60, text: 'Higher high' },
        ].map((point) => (
          <g key={`${point.x}-${point.text}`}>
            <circle cx={point.x} cy={point.y} r="5" fill="#62dce8" stroke="#0a1020" strokeWidth="3" />
            <text x={point.x} y={point.y - 13} textAnchor="middle" fill="#dce6ff" fontSize="10" fontFamily="sans-serif">{point.text}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function LiquidityReferenceDiagram() {
  return (
    <div className="ml-diagram-canvas">
      <svg viewBox="0 0 720 220" role="img" aria-labelledby="ml-liquidity-title ml-liquidity-desc">
        <title id="ml-liquidity-title">Repeated highs as a visible reference zone</title>
        <desc id="ml-liquidity-desc">A simplified price path forms two similar swing highs. A dashed band marks the visible reference area and does not indicate confirmed orders.</desc>
        <path d="M42 185H680M42 140H680M42 95H680M42 50H680" stroke="rgba(154,173,214,.12)" />
        <rect x="42" y="73" width="638" height="18" rx="9" fill="rgba(91,216,231,.06)" stroke="rgba(91,216,231,.35)" strokeDasharray="5 6" />
        <path d="M54 177 L118 137 L174 83 L236 133 L294 84 L352 126 L418 152 L476 106 L528 121 L588 72 L642 101" fill="none" stroke="url(#ml-liquidity-line)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        <defs>
          <linearGradient id="ml-liquidity-line" x1="0" x2="1">
            <stop stopColor="#a894ff" />
            <stop offset="1" stopColor="#5bd8e7" />
          </linearGradient>
        </defs>
        <circle cx="174" cy="83" r="5" fill="#62dce8" stroke="#0a1020" strokeWidth="3" />
        <circle cx="294" cy="84" r="5" fill="#62dce8" stroke="#0a1020" strokeWidth="3" />
        <text x="233" y="62" textAnchor="middle" fill="#dce6ff" fontSize="11" fontFamily="sans-serif">Similar swing highs</text>
        <text x="548" y="67" textAnchor="middle" fill="#82e6ed" fontSize="10" fontFamily="monospace">VISIBLE REFERENCE ZONE</text>
      </svg>
    </div>
  );
}

function StructureBreakDiagram({ kind }: { kind: 'bos' | 'choch' }) {
  const isBos = kind === 'bos';
  const titleId = isBos ? 'ml-bos-title' : 'ml-choch-title';
  const descriptionId = isBos ? 'ml-bos-desc' : 'ml-choch-desc';
  return (
    <figure className="ml-comparison-card">
      <figcaption>{isBos ? 'BOS · break with structure' : 'CHoCH · possible character shift'}</figcaption>
      <div className="ml-diagram-canvas">
        <svg viewBox="0 0 340 170" role="img" aria-labelledby={`${titleId} ${descriptionId}`}>
          <title id={titleId}>{isBos ? 'Break of Structure example' : 'Change of Character example'}</title>
          <desc id={descriptionId}>{isBos
            ? 'A simplified rising swing path breaks above a prior swing high. This describes a structural break, not an entry.'
            : 'A simplified rising swing path breaks below a prior higher low. This may indicate a change in character, not an entry.'}</desc>
          <path d="M20 143H322M20 102H322M20 61H322" stroke="rgba(154,173,214,.12)" />
          {isBos ? (
            <>
              <path d="M24 131 L72 91 L112 118 L154 68 L197 96 L236 46 L271 73 L313 28" fill="none" stroke="#8f80f0" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M182 46H322" stroke="#5bd8e7" strokeWidth="1.5" strokeDasharray="5 5" />
              <text x="186" y="39" fill="#82e6ed" fontSize="9" fontFamily="monospace">PRIOR SWING HIGH</text>
              <text x="272" y="122" fill="#b8abff" fontSize="10" fontFamily="monospace">BOS</text>
            </>
          ) : (
            <>
              <path d="M24 135 L70 95 L111 120 L152 64 L193 92 L232 48 L266 79 L313 111" fill="none" stroke="#8f80f0" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M164 92H322" stroke="#5bd8e7" strokeWidth="1.5" strokeDasharray="5 5" />
              <text x="167" y="85" fill="#82e6ed" fontSize="9" fontFamily="monospace">PRIOR HIGHER LOW</text>
              <text x="253" y="135" fill="#b8abff" fontSize="10" fontFamily="monospace">POSSIBLE CHoCH</text>
            </>
          )}
        </svg>
      </div>
      <p>{isBos
        ? 'A break beyond a prior swing in the existing direction is described as BOS.'
        : 'A break against the prior swing sequence may suggest a shift. It still needs context and confirmation.'}</p>
    </figure>
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

  return null;
}
