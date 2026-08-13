'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getAssetTelemetry } from '@/lib/api/endpoints';
import type { AssetTelemetryResponse } from '@/types/backend';
import { useApiResource } from './useApiResource';

/** The channels the console draws, and where each one comes from. */
export interface ChannelSpec {
  /** Sensor code in the Vitpur seed. */
  sensor: string;
  /** Asset the sensor hangs off — telemetry is fetched per asset. */
  asset: string;
  label: string;
  unit: string;
  decimals?: number;
  /** Used only while the backend is unreachable, to keep the charts alive. */
  base: number;
  amplitude: number;
}

export const CHANNELS: Record<string, ChannelSpec> = {
  flow: { sensor: 'SNS-PMP-01-FLW', asset: 'PMP-01', label: 'Flow (LPM)', unit: 'LPM', base: 850, amplitude: 26 },
  up: { sensor: 'SNS-PMP-01-PRU', asset: 'PMP-01', label: 'Upstream Pressure (m)', unit: 'm', decimals: 1, base: 32.4, amplitude: 0.9 },
  tail: { sensor: 'SNS-ZONE-A-PRT', asset: 'ZONE-A', label: 'Tail-End Pressure (m)', unit: 'm', decimals: 1, base: 18.5, amplitude: 0.5 },
  oht: { sensor: 'SNS-OHT-01-LVL', asset: 'OHT-01', label: 'OHT Level (m)', unit: 'm', decimals: 2, base: 3.4, amplitude: 0.06 },
  kw: { sensor: 'SNS-PMP-01-ENR', asset: 'PMP-01', label: 'Pump Energy (kW)', unit: 'kW', decimals: 1, base: 6.4, amplitude: 0.14 },
  vflow: { sensor: 'SNS-ZONE-A-FLW', asset: 'ZONE-A', label: 'Zone A Flow (LPM)', unit: 'LPM', base: 420, amplitude: 18 },
  vtail: { sensor: 'SNS-ZONE-A-PRT', asset: 'ZONE-A', label: 'Zone A Tail Pressure (m)', unit: 'm', decimals: 1, base: 18.5, amplitude: 0.35 },
};

/** Assets that between them carry every channel above. */
const TELEMETRY_ASSETS = ['PMP-01', 'OHT-01', 'ZONE-A'];

const POINTS = 70;

// ─── Synthetic fallback ──────────────────────────────────────
function initSeries(spec: ChannelSpec): number[] {
  return Array.from(
    { length: POINTS },
    () => spec.base + (Math.random() - 0.5) * spec.amplitude * 2,
  );
}

function stepSeries(data: number[], spec: ChannelSpec): number[] {
  const last = data.length ? data[data.length - 1] : spec.base;
  const next = [
    ...data,
    last + (Math.random() - 0.5) * spec.amplitude * 0.65 + (spec.base - last) * 0.12,
  ];
  if (next.length > POINTS) next.shift();
  return next;
}

function syntheticSeries(): Record<string, number[]> {
  const out: Record<string, number[]> = {};
  for (const [key, spec] of Object.entries(CHANNELS)) out[key] = initSeries(spec);
  return out;
}

// ─── Live series ─────────────────────────────────────────────
function seriesFromTelemetry(
  responses: AssetTelemetryResponse[],
): { series: Record<string, number[]>; units: Record<string, string> } {
  // sensor_code → the sensor's readings, oldest first.
  const bySensorCode = new Map<string, number[]>();
  const unitByCode = new Map<string, string>();

  for (const response of responses) {
    const codeById = new Map(response.sensors.map((s) => [s.id, s.sensor_code]));
    for (const sensor of response.sensors) unitByCode.set(sensor.sensor_code, sensor.unit);

    const ordered = [...response.readings].sort((a, b) => a.ts.localeCompare(b.ts));
    for (const reading of ordered) {
      if (reading.value === null) continue;
      const code = codeById.get(reading.sensor_id);
      if (!code) continue;
      const bucket = bySensorCode.get(code) ?? [];
      bucket.push(reading.value);
      bySensorCode.set(code, bucket);
    }
  }

  const series: Record<string, number[]> = {};
  const units: Record<string, string> = {};
  for (const [key, spec] of Object.entries(CHANNELS)) {
    const values = bySensorCode.get(spec.sensor) ?? [];
    series[key] = values.slice(-POINTS);
    units[key] = unitByCode.get(spec.sensor) ?? spec.unit;
  }
  return { series, units };
}

/**
 * Live telemetry for the console's sparklines.
 *
 * Reads the real sensor history through `/assets/{code}/telemetry`. If the
 * backend is unreachable the hook keeps drawing a synthetic series so the
 * demo does not present five empty charts — `live` says which is on screen.
 */
export function useTelemetryStream(intervalMs = 5_000) {
  const telemetry = useApiResource(
    (signal) =>
      Promise.all(
        TELEMETRY_ASSETS.map((asset) =>
          getAssetTelemetry(asset, { hours: 6, limit: 4000, signal }),
        ),
      ),
    { intervalMs },
  );

  const live = telemetry.data !== null;

  const liveSeries = useMemo(
    () => (telemetry.data ? seriesFromTelemetry(telemetry.data) : null),
    [telemetry.data],
  );

  // Synthetic state only advances while the backend is unreachable.
  const [fallback, setFallback] = useState<Record<string, number[]>>(syntheticSeries);
  const specsRef = useRef(CHANNELS);

  useEffect(() => {
    if (live) return;
    const timer = setInterval(() => {
      setFallback((prev) => {
        const next: Record<string, number[]> = {};
        for (const [key, spec] of Object.entries(specsRef.current)) {
          next[key] = stepSeries(prev[key] ?? initSeries(spec), spec);
        }
        return next;
      });
    }, 1200);
    return () => clearInterval(timer);
  }, [live]);

  const series = liveSeries?.series ?? fallback;

  const getLatest = useCallback(
    (key: string) => {
      const arr = series[key];
      return arr && arr.length ? arr[arr.length - 1] : 0;
    },
    [series],
  );

  const formatValue = useCallback(
    (key: string) => {
      const arr = series[key];
      if (!arr || arr.length === 0) return '—';
      const value = arr[arr.length - 1];
      const decimals = CHANNELS[key]?.decimals;
      return decimals
        ? value.toFixed(decimals)
        : Math.round(value).toLocaleString('en-IN');
    },
    [series],
  );

  const unit = useCallback(
    (key: string) => liveSeries?.units[key] ?? CHANNELS[key]?.unit ?? '',
    [liveSeries],
  );

  return { series, formatValue, getLatest, unit, live, refresh: telemetry.refresh };
}
