'use client';
import { useEffect, useRef } from 'react';

export default function WaveAnimation() {
  const w1Ref = useRef<SVGPathElement>(null);
  const w2Ref = useRef<SVGPathElement>(null);

  useEffect(() => {
    let t = 0;
    let animId: number;

    function makePath(amp: number, len: number, off: number, base: number) {
      let d = `M0 220 L0 ${base}`;
      for (let x = 0; x <= 1440; x += 24) {
        d += ` L${x} ${(base + Math.sin(x / len + off) * amp).toFixed(1)}`;
      }
      return d + ' L1440 220 Z';
    }

    function tick() {
      t += 0.012;
      w1Ref.current?.setAttribute('d', makePath(16, 150, t, 96));
      w2Ref.current?.setAttribute('d', makePath(12, 110, -t * 1.35 + 1.2, 140));
      animId = requestAnimationFrame(tick);
    }

    animId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animId);
  }, []);

  return (
    <svg className="wave" viewBox="0 0 1440 220" preserveAspectRatio="none">
      <defs>
        <linearGradient id="wg1" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(14,159,203,.22)" />
          <stop offset="100%" stopColor="rgba(4,18,31,.05)" />
        </linearGradient>
        <linearGradient id="wg2" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(63,198,232,.12)" />
          <stop offset="100%" stopColor="rgba(4,18,31,.03)" />
        </linearGradient>
      </defs>
      <path ref={w1Ref} fill="url(#wg1)" />
      <path ref={w2Ref} fill="url(#wg2)" />
    </svg>
  );
}
