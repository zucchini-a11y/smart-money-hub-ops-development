import { useEffect, useRef } from 'react';

const ENTRY_INDEX = 10;
const TARGET_INDEX = 39;
const ENTRY = 4007.16;
const STOP = 4003.48;
const TARGET = 4033.27;

const sourceCandles: Array<[number, number]> = [
  [4013, 4010], [4010, 4008.5], [4008.5, 4009], [4009, 4011], [4011, 4009.5],
  [4009.5, 4008.8], [4008.8, 4007.5], [4007.5, 4008.2], [4008.2, 4006.5],
  [4006.5, 4006.2], [4007.2, 4006.2], [4006.2, 4006], [4006, 4006.4],
  [4006.4, 4009], [4008.6, 4007.8], [4007.8, 4009.8], [4009.8, 4011.2],
  [4011.2, 4012], [4012, 4011.9], [4011.9, 4014], [4014, 4011.5],
  [4011.5, 4009.8], [4009.8, 4009.6], [4009.6, 4012.5], [4012.5, 4012],
  [4012, 4016.5], [4016.5, 4018.4], [4018.4, 4017], [4017, 4018.2],
  [4018.2, 4017.9], [4017.9, 4020], [4020, 4018.2], [4018.2, 4019.5],
  [4019.5, 4021], [4021, 4020.7], [4020.7, 4022], [4022, 4023],
  [4023, 4024.5], [4024.5, 4027], [4027, 4032.4], [4032.4, 4029],
  [4029, 4027], [4027, 4025.5], [4025.5, 4024.9], [4024.9, 4025.2],
  [4025.2, 4025], [4025, 4025.4], [4025.4, 4027.5], [4027.5, 4026.8],
  [4026.8, 4024.64],
];

function seededRandom(index: number) {
  const value = Math.sin(index * 91.7) * 10000;
  return value - Math.floor(value);
}

const candles = sourceCandles.map(([open, close], index) => {
  let high = Math.max(open, close) + 0.3 + seededRandom(index) * 0.9;
  const low = Math.min(open, close) - 0.3 - seededRandom(index + 50) * 0.9;
  if (index === TARGET_INDEX) high = TARGET;
  return { open, close, high, low };
});

function clamp(value: number) {
  return Math.max(0, Math.min(1, value));
}

function ease(value: number) {
  const bounded = clamp(value);
  return bounded * bounded * (3 - 2 * bounded);
}

export function XauusdTradeAnimation() {
  const storyRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const story = storyRef.current;
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!story || !stage || !canvas || !context) return;

    const site = stage.closest('.vayda-site') ?? stage;
    const palette = getComputedStyle(site);
    const gold = palette.getPropertyValue('--gold').trim() || '#d7bd7b';
    const green = palette.getPropertyValue('--green').trim() || '#8bb99a';
    const text = palette.getPropertyValue('--text').trim() || '#f3f0e7';
    const muted = palette.getPropertyValue('--muted').trim() || '#a5aaa1';
    const ink = palette.getPropertyValue('--ink').trim() || '#0c1112';
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let viewportWidth = 0;
    let viewportHeight = 0;
    let pixelRatio = 1;
    let lastProgress = 0;
    let animationFrame = 0;

    const draw = (scrollProgress: number) => {
      if (!viewportWidth || !viewportHeight) return;
      lastProgress = clamp(scrollProgress);

      const width = viewportWidth;
      const height = viewportHeight;
      const compactLayout = width < 520;
      const left = compactLayout ? 18 : 34;
      const right = compactLayout ? 68 : 94;
      const top = compactLayout ? Math.min(250, height * 0.34) : Math.max(120, height * 0.16);
      const bottom = height - (compactLayout ? 132 : 138);
      const minPrice = 4002;
      const maxPrice = 4035;
      const candleWidth = (width - left - right) / candles.length;
      const yForPrice = (price: number) => top + ((maxPrice - price) / (maxPrice - minPrice)) * (bottom - top);
      const xForCandle = (index: number) => left + index * candleWidth + candleWidth / 2;
      const playhead = lastProgress * candles.length;
      const complete = playhead >= candles.length;
      const currentIndex = Math.min(Math.floor(Math.min(playhead, candles.length - 0.001)), candles.length - 1);
      const fraction = complete ? 1 : playhead - currentIndex;

      context.clearRect(0, 0, width, height);
      context.fillStyle = ink;
      context.fillRect(0, 0, width, height);

      const gridStep = compactLayout ? 4 : 2;
      context.strokeStyle = 'rgba(235,220,181,.13)';
      context.lineWidth = 1;
      context.font = `${compactLayout ? 10 : 12}px "JetBrains Mono", monospace`;
      context.textAlign = 'left';
      for (let price = 4004; price <= 4034; price += gridStep) {
        const y = yForPrice(price);
        context.beginPath();
        context.moveTo(left, y);
        context.lineTo(width - right, y);
        context.stroke();
        context.fillStyle = muted;
        context.fillText(price.toFixed(2), width - right + 8, y + 4);
      }

      if (playhead >= ENTRY_INDEX) {
        const reveal = ease((playhead - ENTRY_INDEX) / 1.5);
        const startX = xForCandle(ENTRY_INDEX) - candleWidth / 2;
        const endIndex = playhead >= TARGET_INDEX
          ? TARGET_INDEX + 1
          : Math.max(playhead, ENTRY_INDEX + 1);
        const endX = left + Math.min(endIndex, TARGET_INDEX + 1) * candleWidth;
        const entryY = yForPrice(ENTRY);
        const stopY = yForPrice(STOP);
        const visiblePeak = playhead >= TARGET_INDEX
          ? TARGET
          : Math.min(
            TARGET,
            Math.max(...candles.slice(ENTRY_INDEX, currentIndex + 1).map((candle) => candle.high)) + 3,
          );
        const profitTopY = yForPrice(Math.max(visiblePeak, ENTRY + 4));

        context.globalAlpha = 0.2 * reveal;
        context.fillStyle = green;
        context.fillRect(startX, profitTopY, endX - startX, entryY - profitTopY);
        context.globalAlpha = 0.18 * reveal;
        context.fillStyle = gold;
        context.fillRect(startX, entryY, endX - startX, stopY - entryY);
        context.globalAlpha = reveal;

        context.strokeStyle = 'rgba(243,240,231,.65)';
        context.setLineDash([6, 6]);
        context.beginPath();
        context.moveTo(startX, entryY);
        context.lineTo(width - right, entryY);
        context.stroke();
        context.setLineDash([]);

        const drawTag = (price: number, label: string, fill: string, foreground = text) => {
          const y = yForPrice(price);
          context.fillStyle = fill;
          context.fillRect(width - right + 3, y - 10, right - 6, 20);
          context.fillStyle = foreground;
          context.font = `600 ${compactLayout ? 9 : 11}px "JetBrains Mono", monospace`;
          context.textAlign = 'center';
          context.fillText(label, width - right / 2, y + 3.5);
        };

        drawTag(ENTRY, ENTRY.toFixed(2), 'rgba(28,36,32,.96)');
        drawTag(STOP, STOP.toFixed(2), gold, ink);
        if (playhead >= TARGET_INDEX - 6) {
          context.globalAlpha = ease((playhead - (TARGET_INDEX - 6)) / 6);
          drawTag(TARGET, TARGET.toFixed(2), 'rgba(28,36,32,.96)');
        }
        if (playhead >= TARGET_INDEX) {
          context.globalAlpha = ease((playhead - TARGET_INDEX) / 1.2);
          context.fillStyle = gold;
          const badgeWidth = compactLayout ? 54 : 70;
          const badgeHeight = compactLayout ? 24 : 28;
          const badgeX = (startX + endX) / 2 - badgeWidth / 2;
          context.fillRect(badgeX, yForPrice(TARGET) + 10, badgeWidth, badgeHeight);
          context.fillStyle = ink;
          context.font = `800 ${compactLayout ? 11 : 14}px Manrope, sans-serif`;
          context.textAlign = 'center';
          context.fillText('TP 7', badgeX + badgeWidth / 2, yForPrice(TARGET) + badgeHeight + 2);
        }
        context.globalAlpha = 1;

        const lineProgress = ease((playhead - ENTRY_INDEX) / (TARGET_INDEX - ENTRY_INDEX));
        if (lineProgress > 0) {
          const startY = entryY;
          const targetX = xForCandle(TARGET_INDEX);
          const targetY = yForPrice(candles[TARGET_INDEX].high);
          context.strokeStyle = 'rgba(243,240,231,.82)';
          context.lineWidth = 1.5;
          context.setLineDash([7, 6]);
          context.beginPath();
          context.moveTo(xForCandle(ENTRY_INDEX), startY);
          context.lineTo(
            xForCandle(ENTRY_INDEX) + (targetX - xForCandle(ENTRY_INDEX)) * lineProgress,
            startY + (targetY - startY) * lineProgress,
          );
          context.stroke();
          context.setLineDash([]);
          context.lineWidth = 1;
        }
      }

      for (let index = 0; index <= currentIndex && index < candles.length; index += 1) {
        const candle = candles[index];
        const candleFraction = index === currentIndex ? fraction : 1;
        const currentClose = candle.open + (candle.close - candle.open) * candleFraction;
        const high = Math.max(candle.open, currentClose)
          + (candle.high - Math.max(candle.open, candle.close)) * candleFraction;
        const low = Math.min(candle.open, currentClose)
          + (candle.low - Math.min(candle.open, candle.close)) * candleFraction;
        const candleColor = candle.close >= candle.open ? green : gold;
        context.fillStyle = candleColor;
        context.strokeStyle = candleColor;
        context.lineWidth = compactLayout ? 1 : 1.5;
        context.beginPath();
        context.moveTo(xForCandle(index), yForPrice(high));
        context.lineTo(xForCandle(index), yForPrice(low));
        context.stroke();
        const bodyTop = yForPrice(Math.max(candle.open, currentClose));
        const bodyHeight = Math.max(1.5, Math.abs(yForPrice(candle.open) - yForPrice(currentClose)));
        context.fillRect(
          xForCandle(index) - Math.max(1, candleWidth * 0.34),
          bodyTop,
          Math.max(2, candleWidth * 0.68),
          bodyHeight,
        );
      }

      const currentCandle = candles[currentIndex];
      const lastPrice = currentCandle.open + (currentCandle.close - currentCandle.open) * fraction;
      context.fillStyle = currentCandle.close >= currentCandle.open ? green : gold;
      context.fillRect(width - right + 3, yForPrice(lastPrice) - 10, right - 6, 20);
      context.fillStyle = ink;
      context.font = `600 ${compactLayout ? 9 : 11}px "JetBrains Mono", monospace`;
      context.textAlign = 'center';
      context.fillText(lastPrice.toFixed(2), width - right / 2, yForPrice(lastPrice) + 3.5);

      const metrics: Array<[string, string]> = [
        ['ENTRY', ENTRY.toFixed(2)],
        ['STOP', STOP.toFixed(2)],
        ['TARGET', TARGET.toFixed(2)],
        ['R:R', '1 : 7.1'],
      ];
      const statsWidth = width - left - right;
      metrics.forEach(([label, value], index) => {
        const x = left + index * (statsWidth / metrics.length) + 4;
        context.textAlign = 'left';
        context.fillStyle = muted;
        context.font = `${compactLayout ? 8 : 10}px "JetBrains Mono", monospace`;
        context.fillText(label, x, height - 70);
        context.fillStyle = text;
        context.font = `600 ${compactLayout ? 10 : 12}px "JetBrains Mono", monospace`;
        context.fillText(value, x, height - 48);
      });

    };

    const resizeCanvas = () => {
      const rect = stage.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      viewportWidth = rect.width;
      viewportHeight = rect.height;
      pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(viewportWidth * pixelRatio);
      canvas.height = Math.round(viewportHeight * pixelRatio);
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      draw(reducedMotion ? 1 : lastProgress);
    };

    const updateFromScroll = () => {
      if (reducedMotion || animationFrame) return;
      animationFrame = window.requestAnimationFrame(() => {
        animationFrame = 0;
        const range = story.offsetHeight - stage.offsetHeight;
        if (range <= 0) {
          draw(0);
          return;
        }
        const stickyTop = Number.parseFloat(getComputedStyle(stage).top) || 0;
        const storyTop = story.getBoundingClientRect().top;
        draw((stickyTop - storyTop) / range);
      });
    };

    resizeCanvas();
    updateFromScroll();

    const resizeObserver = typeof ResizeObserver !== 'undefined'
      ? new ResizeObserver(resizeCanvas)
      : null;
    resizeObserver?.observe(stage);
    window.addEventListener('resize', resizeCanvas);
    if (!reducedMotion) {
      window.addEventListener('scroll', updateFromScroll, { passive: true });
    } else {
      draw(1);
    }

    return () => {
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      resizeObserver?.disconnect();
      window.removeEventListener('resize', resizeCanvas);
      window.removeEventListener('scroll', updateFromScroll);
    };
  }, []);

  return <section id="chart-study" className="vs-chart-scroll-story" ref={storyRef} aria-label="Scroll-driven XAUUSD trade example">
    <div className="vs-chart-stage" ref={stageRef}>
      <canvas
        className="vs-chart-canvas"
        ref={canvasRef}
        role="img"
        aria-label="Scroll-driven illustrative XAUUSD long setup: entry 4007.16, stop 4003.48, target 4033.27, and a 1 to 7.1 reward-to-risk example. Not live market data or financial advice."
      />
      <div className="vs-chart-glow" aria-hidden="true" />
      <header className="vs-chart-head">
        <div>
          <div className="vs-chart-title">XAUUSD · Gold long example</div>
          <div className="vs-chart-caption">SCROLL TO TRACE THE SETUP</div>
        </div>
        <span className="vs-chart-tag">ILLUSTRATIVE · NOT LIVE</span>
      </header>
      <p className="vs-chart-foot">Simulated example · not live market data or financial advice.</p>
    </div>
  </section>;
}
