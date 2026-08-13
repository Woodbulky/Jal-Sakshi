'use client';
import { useMemo } from 'react';
import SparklineChart from '@/components/telemetry/SparklineChart';
import { CHANNELS, useTelemetryStream } from '@/hooks/useTelemetryStream';
import { useNetwork } from '@/hooks/useNetwork';
import { fmtSeconds } from '@/lib/adapters';

const TILES = [
  { key: 'flow', color: '#0E9FCB', alarm: false },
  { key: 'up', color: '#F0A11B', alarm: false },
  { key: 'tail', color: '#EF4444', alarm: true },
  { key: 'oht', color: '#0E9FCB', alarm: false },
  { key: 'kw', color: '#22B463', alarm: false },
];

export default function TelemetryPage() {
  const { series, formatValue, unit, live } = useTelemetryStream();
  const { sensors, sensorHealth, untrusted, assetCodeById } = useNetwork();

  const healthByCode = useMemo(
    () => new Map(sensorHealth.map((h) => [h.sensor_code, h])),
    [sensorHealth],
  );

  const online = sensors.filter((s) => !untrusted.has(s.sensor_code)).length;

  return (
    <div className="page-container on">
      <div className="page-head">
        <div>
          <h1>Telemetry Overview</h1>
          <div className="sub">
            Live sensor data across the Vitpur distribution network
            {!live && ' · backend unreachable, showing a synthetic trace'}
          </div>
        </div>
        <div className="row gap8">
          <span className="badge b-normal"><span className="dot" />{online} sensors trusted</span>
          <span className="badge b-off"><span className="dot" />{untrusted.size} untrusted</span>
          <span className="badge b-neutral">{sensors.length} total</span>
        </div>
      </div>

      <div className="grid g-5" style={{ gridTemplateColumns: 'repeat(5,1fr)', marginBottom: 12 }}>
        {TILES.map(ch => (
          <div key={ch.key} className={`tel ${ch.alarm ? 'alarm' : ''}`}>
            <div className="tl">{CHANNELS[ch.key].label.replace(/\s*\(.*\)$/, '')} ({unit(ch.key)})</div>
            <div className="tv">{formatValue(ch.key)}</div>
            <SparklineChart data={series[ch.key] || []} color={ch.color} />
          </div>
        ))}
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="card-h">
          <h3>Sensor Status Register</h3>
          <span className="badge b-neutral">{sensors.length} sensors</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Sensor</th><th>Type</th><th>Asset</th><th>Trusted</th>
                <th>Last Reading</th><th>Seen at</th><th>Issues</th>
              </tr>
            </thead>
            <tbody>
              {sensors.length === 0 && (
                <tr><td colSpan={7} className="t-sm muted" style={{ padding: 14 }}>
                  No sensors — the network endpoint is unavailable.
                </td></tr>
              )}
              {sensors.map((sensor) => {
                const health = healthByCode.get(sensor.sensor_code);
                const trusted = health ? health.trusted : !untrusted.has(sensor.sensor_code);
                return (
                  <tr key={sensor.id}>
                    <td className="mono strong">{sensor.sensor_code}</td>
                    <td>{sensor.sensor_type.replace(/_/g, ' ').toLowerCase()}</td>
                    <td className="mono">{assetCodeById.get(sensor.asset_id) ?? '—'}</td>
                    <td>
                      <span className={`badge b-${trusted ? 'normal' : 'off'}`}>
                        <span className="dot" />{trusted ? 'Trusted' : 'Untrusted'}
                      </span>
                    </td>
                    <td className="mono">
                      {sensor.latest?.value != null
                        ? `${sensor.latest.value.toFixed(2)} ${sensor.unit}`
                        : '—'}
                    </td>
                    <td className="mono">{fmtSeconds(sensor.latest?.ts ?? sensor.last_seen_at)}</td>
                    <td className="t-sm muted">
                      {health?.issues.length ? health.issues.join(', ').toLowerCase() : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="card-f">
          <span className="t-sm muted">
            Trust is guardrail 1: an untrusted instrument may not raise an incident, and may
            not close one. A sensor goes untrusted when it is stale, flatlined or out of range.
          </span>
        </div>
      </div>
    </div>
  );
}
