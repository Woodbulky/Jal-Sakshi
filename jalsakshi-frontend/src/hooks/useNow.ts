'use client';
import { useEffect, useState } from 'react';

/**
 * A ticking clock as state.
 *
 * Countdowns need the current time, and reading `Date.now()` during render is
 * impure — the same render would produce a different result on replay. Holding
 * it in state makes every "time remaining" on screen a normal render input.
 */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);

  return now;
}
