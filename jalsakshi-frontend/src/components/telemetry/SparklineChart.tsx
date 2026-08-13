'use client';
import { useEffect, useRef } from 'react';

interface Props {
  data: number[];
  color: string;
  fill?: boolean;
  height?: number;
}

export default function SparklineChart({ data, color, fill = true, height = 40 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || data.length < 2) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = cv.clientWidth || 220;
    const h = height;
    cv.width = w * dpr;
    cv.height = h * dpr;
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const mn = Math.min(...data), mx = Math.max(...data), rg = (mx - mn) || 1;
    const X = (i: number) => (i / (data.length - 1)) * w;
    const Y = (v: number) => h - 3 - ((v - mn) / rg) * (h - 8);

    if (fill) {
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, color + '44');
      g.addColorStop(1, color + '00');
      ctx.beginPath();
      ctx.moveTo(0, h);
      data.forEach((v, i) => ctx.lineTo(X(i), Y(v)));
      ctx.lineTo(w, h);
      ctx.closePath();
      ctx.fillStyle = g;
      ctx.fill();
    }

    ctx.beginPath();
    data.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // Trailing dot
    ctx.beginPath();
    ctx.arc(X(data.length - 1), Y(data[data.length - 1]), 2.4, 0, 7);
    ctx.fillStyle = color;
    ctx.fill();
  }, [data, color, fill, height]);

  return (
    <canvas
      ref={canvasRef}
      style={{ display: 'block', width: '100%', height }}
    />
  );
}
