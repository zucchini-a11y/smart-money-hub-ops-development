import { useEffect, useRef } from 'react';

type Candle = { open: number; close: number; high: number; low: number };

function clamp(value: number) {
  return Math.max(0.1, Math.min(0.9, value));
}

export function VaydaHeroAnimation() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const stage = canvas?.parentElement;
    const context = canvas?.getContext('2d');
    if (!canvas || !stage || !context) return;

    const site = stage.closest('.vayda-site') ?? stage;
    const palette = getComputedStyle(site);
    const gold = palette.getPropertyValue('--gold').trim() || '#d7bd7b';
    const green = palette.getPropertyValue('--green').trim() || '#8bb99a';
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let level = 0.35;
    const makeCandle = (): Candle => {
      const open = level;
      level = clamp(level + (0.5 - level) * 0.05 + (Math.random() - 0.46) * 0.09);
      const close = level;
      return {
        open,
        close,
        high: Math.min(0.97, Math.max(open, close) + Math.random() * 0.04),
        low: Math.max(0.03, Math.min(open, close) - Math.random() * 0.04),
      };
    };

    const candles = Array.from({ length: 80 }, makeCandle);
    let width = 0;
    let height = 0;
    let pixelRatio = 1;
    let offset = 0;
    let lastFrame = 0;
    let startedAt = performance.now();
    let frame = 0;
    let visible = false;

    const paint = (now: number, advance: boolean) => {
      if (!width || !height) return;
      const elapsed = lastFrame ? Math.min(now - lastFrame, 50) : 0;
      lastFrame = now;
      const candleWidth = Math.max(16, width / 45);

      if (advance && !reducedMotion) {
        offset += elapsed * 0.018;
        while (offset >= candleWidth) {
          offset -= candleWidth;
          candles.shift();
          candles.push(makeCandle());
        }
      }

      context.clearRect(0, 0, width, height);
      const reveal = Math.min(1, Math.max(0, (now - startedAt) / 1800));
      context.globalAlpha = 0.18 * reveal;
      context.lineWidth = 1;
      const top = height * 0.12;
      const bottom = height * 0.88;
      const yForValue = (value: number) => bottom - value * (bottom - top);

      candles.forEach((candle, index) => {
        const x = index * candleWidth - offset + candleWidth / 2;
        if (x < -candleWidth || x > width + candleWidth) return;
        const isRising = candle.close >= candle.open;
        context.strokeStyle = isRising ? green : gold;
        context.fillStyle = isRising ? green : gold;
        context.beginPath();
        context.moveTo(x, yForValue(candle.high));
        context.lineTo(x, yForValue(candle.low));
        context.stroke();
        context.fillRect(
          x - candleWidth * 0.3,
          yForValue(Math.max(candle.open, candle.close)),
          candleWidth * 0.6,
          Math.max(2, Math.abs(yForValue(candle.open) - yForValue(candle.close))),
        );
      });

      context.globalAlpha = 1;
    };

    const fit = () => {
      const bounds = stage.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      width = bounds.width;
      height = bounds.height;
      pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      paint(performance.now(), false);
    };

    const animate = (now: number) => {
      frame = 0;
      if (!visible || reducedMotion) return;
      paint(now, true);
      frame = window.requestAnimationFrame(animate);
    };

    const start = () => {
      if (!visible || reducedMotion || frame) return;
      frame = window.requestAnimationFrame(animate);
    };

    const stop = () => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
      lastFrame = 0;
    };

    fit();
    const resizeObserver = typeof ResizeObserver !== 'undefined'
      ? new ResizeObserver(fit)
      : null;
    resizeObserver?.observe(stage);
    window.addEventListener('resize', fit);

    const visibilityObserver = typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver(([entry]) => {
        visible = entry.isIntersecting;
        if (visible) start();
        else stop();
      }, { rootMargin: '80px 0px' })
      : null;

    if (visibilityObserver) {
      visibilityObserver.observe(stage);
    } else {
      visible = true;
      start();
    }

    return () => {
      stop();
      resizeObserver?.disconnect();
      visibilityObserver?.disconnect();
      window.removeEventListener('resize', fit);
    };
  }, []);

  return <div className="vs-hero-animation" aria-hidden="true">
    <canvas ref={canvasRef} className="vs-hero-animation-canvas" />
  </div>;
}
