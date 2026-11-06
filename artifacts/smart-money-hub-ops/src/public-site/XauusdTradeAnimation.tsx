import { useEffect, useRef, useState } from 'react';
import { RotateCcw } from 'lucide-react';

const WIDTH = 960;
const HEIGHT = 540;
const ENTRY_INDEX = 10;
const TARGET_INDEX = 39;
const CANDLE_MS = 190;
const END_HOLD_MS = 2600;
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

function ease(value: number) {
  const clamped = Math.max(0, Math.min(1, value));
  return clamped * clamped * (3 - 2 * clamped);
}

export function XauusdTradeAnimation() {
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [replayKey, setReplayKey] = useState(0);

  useEffect(() => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!stage || !canvas || !context) return;

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const palette = getComputedStyle(stage.closest('.vayda-site') ?? stage);
    const gold = palette.getPropertyValue('--gold').trim() || '#d7bd7b';
    const brightGold = palette.getPropertyValue('--gold-bright').trim() || '#ecd79e';
    const green = palette.getPropertyValue('--green').trim() || '#8bb99a';
    const text = palette.getPropertyValue('--text').trim() || '#f3f0e7';
    const muted = palette.getPropertyValue('--muted').trim() || '#a5aaa1';
    const ink = palette.getPropertyValue('--ink').trim() || '#0c1112';

    const left = 28;
    const right = 106;
    const top = 78;
    const bottom = 432;
    const minPrice = 4002;
    const maxPrice = 4035;
    const candleWidth = (WIDTH - left - right) / candles.length;
    const yForPrice = (price: number) => top + ((maxPrice - price) / (maxPrice - minPrice)) * (bottom - top);
    const xForCandle = (index: number) => left + index * candleWidth + candleWidth / 2;
    const sequenceDuration = candles.length * CANDLE_MS;
    const cycleDuration = sequenceDuration + END_HOLD_MS;

    canvas.width = WIDTH;
    canvas.height = HEIGHT;

    const drawTag = (price: number, label: string, fill: string, foreground = text) => {
      const y = yForPrice(price);
      context.fillStyle = fill;
      context.fillRect(WIDTH - right + 4, y - 13, right - 8, 26);
      context.fillStyle = foreground;
      context.font = `600 ${canvas.clientWidth < 430 ? 18 : 16}px "JetBrains Mono", monospace`;
      context.textAlign = 'center';
      context.fillText(label, WIDTH - right / 2, y + 5);
    };

    const draw = (playhead: number) => {
      const compactLayout = canvas.clientWidth < 430;
      const complete = playhead >= candles.length;
      const progress = complete ? candles.length : Math.max(0, playhead);
      const currentIndex = Math.min(Math.floor(Math.min(progress, candles.length - 0.001)), candles.length - 1);
      const fraction = complete ? 1 : progress - currentIndex;

      context.clearRect(0, 0, WIDTH, HEIGHT);
      context.fillStyle = ink;
      context.fillRect(0, 0, WIDTH, HEIGHT);

      context.strokeStyle = 'rgba(235,220,181,.12)';
      context.lineWidth = 1;
      context.font = `${compactLayout ? 21 : 17}px "JetBrains Mono", monospace`;
      context.textAlign = 'left';
      for (let price = 4004; price <= 4034; price += compactLayout ? 4 : 2) {
        const y = yForPrice(price);
        context.beginPath();
        context.moveTo(left, y);
        context.lineTo(WIDTH - right, y);
        context.stroke();
        context.fillStyle = muted;
        context.fillText(price.toFixed(2), WIDTH - right + 9, y + 5);
      }

      if (progress >= ENTRY_INDEX) {
        const reveal = ease((progress - ENTRY_INDEX) / 1.5);
        const startX = xForCandle(ENTRY_INDEX) - candleWidth / 2;
        const endIndex = progress >= TARGET_INDEX ? TARGET_INDEX + 1 : Math.max(progress, ENTRY_INDEX + 1);
        const endX = left + Math.min(endIndex, TARGET_INDEX + 1) * candleWidth;
        const entryY = yForPrice(ENTRY);
        const stopY = yForPrice(STOP);
        const visiblePeak = progress >= TARGET_INDEX
          ? TARGET
          : Math.min(TARGET, Math.max(...candles.slice(ENTRY_INDEX, currentIndex + 1).map((candle) => candle.high)) + 3);
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
        context.lineTo(WIDTH - right, entryY);
        context.stroke();
        context.setLineDash([]);
        drawTag(ENTRY, ENTRY.toFixed(2), 'rgba(28,36,32,.96)');
        drawTag(STOP, STOP.toFixed(2), gold, ink);

        if (progress >= TARGET_INDEX - 6) {
          context.globalAlpha = ease((progress - (TARGET_INDEX - 6)) / 6);
          drawTag(TARGET, TARGET.toFixed(2), 'rgba(28,36,32,.96)');
        }
        if (progress >= TARGET_INDEX) {
          context.globalAlpha = ease((progress - TARGET_INDEX) / 1.2);
          context.fillStyle = gold;
          const badgeX = (startX + endX) / 2 - 38;
          context.fillRect(badgeX, yForPrice(TARGET) + 12, 76, 30);
          context.fillStyle = ink;
          context.font = '800 18px Manrope, sans-serif';
          context.textAlign = 'center';
          context.fillText('TP 7', badgeX + 38, yForPrice(TARGET) + 33);
        }
        context.globalAlpha = 1;

        const lineProgress = ease((progress - ENTRY_INDEX) / (TARGET_INDEX - ENTRY_INDEX));
        if (lineProgress > 0) {
          const startX = xForCandle(ENTRY_INDEX);
          const startY = entryY;
          const targetX = xForCandle(TARGET_INDEX);
          const targetY = yForPrice(candles[TARGET_INDEX].high);
          context.strokeStyle = 'rgba(243,240,231,.82)';
          context.lineWidth = 1.5;
          context.setLineDash([7, 6]);
          context.beginPath();
          context.moveTo(startX, startY);
          context.lineTo(startX + (targetX - startX) * lineProgress, startY + (targetY - startY) * lineProgress);
          context.stroke();
          context.setLineDash([]);
          context.lineWidth = 1;
        }
      }

      for (let index = 0; index <= currentIndex && index < candles.length; index += 1) {
        const candle = candles[index];
        const currentClose = candle.open + (candle.close - candle.open) * (index === currentIndex ? fraction : 1);
        const high = Math.max(candle.open, currentClose) + (candle.high - Math.max(candle.open, candle.close)) * (index === currentIndex ? fraction : 1);
        const low = Math.min(candle.open, currentClose) + (candle.low - Math.min(candle.open, candle.close)) * (index === currentIndex ? fraction : 1);
        const candleColor = candle.close >= candle.open ? green : gold;
        context.fillStyle = candleColor;
        context.strokeStyle = candleColor;
        context.lineWidth = 2;
        context.beginPath();
        context.moveTo(xForCandle(index), yForPrice(high));
        context.lineTo(xForCandle(index), yForPrice(low));
        context.stroke();
        const bodyTop = yForPrice(Math.max(candle.open, currentClose));
        const bodyHeight = Math.max(2, Math.abs(yForPrice(candle.open) - yForPrice(currentClose)));
        context.fillRect(xForCandle(index) - candleWidth * 0.34, bodyTop, candleWidth * 0.68, bodyHeight);
      }

      const currentCandle = candles[currentIndex];
      const lastPrice = currentCandle.open + (currentCandle.close - currentCandle.open) * fraction;
      drawTag(lastPrice, lastPrice.toFixed(2), currentCandle.close >= currentCandle.open ? green : gold, ink);

      context.textAlign = 'left';
      context.font = '16px "JetBrains Mono", monospace';
      const metrics: Array<[string, string]> = [
        ['ENTRY', ENTRY.toFixed(2)],
        ['STOP', STOP.toFixed(2)],
        ['TARGET', TARGET.toFixed(2)],
        ['R:R', '1 : 7.1'],
      ];
      metrics.forEach(([label, value], index) => {
        const x = left + 8 + index * 142;
        context.fillStyle = muted;
        context.font = `${compactLayout ? 18 : 16}px "JetBrains Mono", monospace`;
        context.fillText(label, x, 475);
        context.fillStyle = text;
        context.font = `600 ${compactLayout ? 26 : 23}px "JetBrains Mono", monospace`;
        context.fillText(value, x, 506);
        context.font = `${compactLayout ? 18 : 16}px "JetBrains Mono", monospace`;
      });
      context.fillStyle = brightGold;
      context.textAlign = 'right';
      context.font = `600 ${compactLayout ? 14 : 16}px "JetBrains Mono", monospace`;
      context.fillText(
        progress < ENTRY_INDEX ? 'WAITING FOR ENTRY' : progress >= TARGET_INDEX ? 'TARGET 7 REACHED' : 'TRADE EXAMPLE',
        WIDTH - right,
        506,
      );
    };

    let animationFrame = 0;
    let isVisible = false;
    let isActive = false;
    let startedAt = performance.now();

    const stop = () => {
      isActive = false;
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      animationFrame = 0;
    };

    const frame = (now: number) => {
      if (!isActive) return;
      const elapsed = (now - startedAt) % cycleDuration;
      draw(Math.min(elapsed / CANDLE_MS, candles.length));
      animationFrame = window.requestAnimationFrame(frame);
    };

    const start = () => {
      if (prefersReducedMotion || isActive || !isVisible || document.hidden) return;
      isActive = true;
      animationFrame = window.requestAnimationFrame(frame);
    };

    const onVisibilityChange = () => {
      if (document.hidden) stop();
      else start();
    };

    if (prefersReducedMotion) {
      draw(candles.length);
    } else {
      draw(0);
      if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver(([entry]) => {
          isVisible = entry.isIntersecting;
          if (isVisible) start();
          else stop();
        }, { threshold: 0.18 });
        observer.observe(stage);
        document.addEventListener('visibilitychange', onVisibilityChange);
        return () => {
          stop();
          observer.disconnect();
          document.removeEventListener('visibilitychange', onVisibilityChange);
        };
      }
      isVisible = true;
      start();
    }

    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [replayKey]);

  return <div className="vs-chart-stage" ref={stageRef}>
    <div className="vs-chart-orbit" aria-hidden="true" />
    <figure className="vs-chart-frame">
      <div className="vs-chart-head">
        <div>
          <div className="vs-chart-title">XAUUSD · Gold long example</div>
          <div className="vs-chart-caption">ILLUSTRATIVE TRADE STUDY</div>
        </div>
        <span className="vs-chart-tag">EDUCATIONAL</span>
      </div>
      <canvas
        className="vs-chart-canvas"
        ref={canvasRef}
        width={WIDTH}
        height={HEIGHT}
        role="img"
        aria-label="Animated illustrative XAUUSD long setup showing entry 4007.16, stop 4003.48, target 4033.27, and a 1 to 7.1 reward-to-risk example. Not live market data or financial advice."
      />
      <figcaption className="vs-chart-foot">
        <span>Simulated example · not live market data or advice.</span>
        <button
          className="vs-chart-replay"
          type="button"
          onClick={() => setReplayKey((key) => key + 1)}
          aria-label="Replay the XAUUSD chart animation"
        >
          <RotateCcw size={13} aria-hidden="true" />
          Replay
        </button>
      </figcaption>
    </figure>
  </div>;
}
