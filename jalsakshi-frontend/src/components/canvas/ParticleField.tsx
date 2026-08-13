'use client';
import { useEffect, useRef } from 'react';

interface Props {
  count?: number;
  linkDistance?: number;
  className?: string;
}

export default function ParticleField({ count = 70, linkDistance = 150, className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let W = 0, H = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    interface Particle {
      x: number; y: number; vx: number; vy: number;
      r: number; ph: number; hot: boolean;
    }
    let pts: Particle[] = [];
    let animId: number;

    function seed() {
      pts = [];
      for (let i = 0; i < count; i++) {
        pts.push({
          x: Math.random() * W,
          y: Math.random() * H,
          vx: (Math.random() - 0.5) * 0.22,
          vy: (Math.random() - 0.5) * 0.22,
          r: Math.random() * 1.6 + 0.7,
          ph: Math.random() * Math.PI * 2,
          hot: Math.random() < 0.12,
        });
      }
    }

    function resize() {
      const r = canvas!.getBoundingClientRect();
      W = r.width;
      H = r.height;
      canvas!.width = W * dpr;
      canvas!.height = H * dpr;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (pts.length === 0) seed();
    }

    function frame(t: number) {
      if (!W) resize();
      ctx!.clearRect(0, 0, W, H);

      for (let i = 0; i < pts.length; i++) {
        const p = pts[i];
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > W) p.vx *= -1;
        if (p.y < 0 || p.y > H) p.vy *= -1;

        for (let j = i + 1; j < pts.length; j++) {
          const q = pts[j];
          const dx = p.x - q.x, dy = p.y - q.y;
          const d = Math.hypot(dx, dy);
          if (d < linkDistance) {
            const a = (1 - d / linkDistance) * 0.30;
            ctx!.strokeStyle = `rgba(90,180,220,${a.toFixed(3)})`;
            ctx!.lineWidth = 0.7;
            ctx!.beginPath();
            ctx!.moveTo(p.x, p.y);
            ctx!.lineTo(q.x, q.y);
            ctx!.stroke();
          }
        }
      }

      for (const p of pts) {
        const pulse = 0.55 + 0.45 * Math.sin(t / 900 + p.ph);
        ctx!.beginPath();
        ctx!.arc(p.x, p.y, p.r * (p.hot ? 1.5 : 1), 0, 7);
        ctx!.fillStyle = p.hot
          ? `rgba(99,220,250,${(0.5 + 0.5 * pulse).toFixed(2)})`
          : `rgba(150,205,230,${(0.28 + 0.30 * pulse).toFixed(2)})`;
        ctx!.fill();
        if (p.hot) {
          ctx!.beginPath();
          ctx!.arc(p.x, p.y, p.r * (4 + 5 * pulse), 0, 7);
          ctx!.fillStyle = `rgba(63,198,232,${(0.06 * (1 - pulse)).toFixed(3)})`;
          ctx!.fill();
        }
      }

      animId = requestAnimationFrame(frame);
    }

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();
    animId = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(animId);
      ro.disconnect();
    };
  }, [count, linkDistance]);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
    />
  );
}
