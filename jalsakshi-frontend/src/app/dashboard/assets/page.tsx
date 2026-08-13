'use client';
import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { getAssetHealth } from '@/lib/api/endpoints';
import { useApiResource } from '@/hooks/useApiResource';
import { useNetwork } from '@/hooks/useNetwork';
import {
  SEVERITY_LABEL,
  faultLabel,
  fmtDateTime,
  fmtDuration,
  incidentRef,
  severityFromScore,
  workOrderStatusLabel,
} from '@/lib/adapters';

function AssetHealthView() {
  const router = useRouter();
  const search = useSearchParams();
  const { assets } = useNetwork({ intervalMs: 30_000 });
  const [code, setCode] = useState<string>(search.get('asset') ?? 'VLV-01');
  const trendRef = useRef<HTMLCanvasElement>(null);

  const resource = useApiResource(
    (signal) => getAssetHealth(code, { signal }),
    { intervalMs: 20_000, deps: [code] },
  );

  const detail = resource.data;
  const health = detail?.health ?? null;
  /** The backend scores health 0–1; the console's ring is out of 100. */
  const score = health ? Math.round(health.health_score * 100) : null;

  const orders = detail?.work_orders ?? [];
  const ttwrs = orders
    .map((o) => o.ttwr_minutes)
    .filter((v): v is number => v !== null && v !== undefined);

  const trend = useMemo(() => {
    // The health record keeps a history of past scores; fall back to the
    // current score alone so the chart still renders on a fresh asset.
    const points = (health?.history ?? [])
      .map((h) => (typeof h.health_score === 'number' ? h.health_score * 100 : null))
      .filter((v): v is number => v !== null);
    return points.length >= 2 ? points : score !== null ? [score, score] : [];
  }, [health, score]);

  useEffect(() => {
    const cv = trendRef.current;
    if (!cv || !cv.clientWidth || trend.length < 2) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = cv.clientWidth;
    const ht = cv.clientHeight || 130;
    cv.width = w * dpr;
    cv.height = ht * dpr;
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, ht);

    const X = (i: number) => 8 + (i / (trend.length - 1)) * (w - 16);
    const Y = (v: number) => ht - 16 - (Math.max(0, Math.min(100, v)) / 100) * (ht - 30);

    ctx.strokeStyle = '#E7EDF3'; ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const y = 10 + (i * (ht - 26)) / 3;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }
    const ty = Y(70);
    ctx.setLineDash([4, 4]); ctx.strokeStyle = 'rgba(198,40,40,.5)';
    ctx.beginPath(); ctx.moveTo(0, ty); ctx.lineTo(w, ty); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(198,40,40,.75)'; ctx.font = '600 9px Inter';
    ctx.fillText('Review threshold 70', 8, ty - 4);

    const g = ctx.createLinearGradient(0, 0, 0, ht);
    g.addColorStop(0, 'rgba(240,161,27,.30)'); g.addColorStop(1, 'rgba(240,161,27,0)');
    ctx.beginPath(); ctx.moveTo(X(0), ht);
    trend.forEach((v, i) => ctx.lineTo(X(i), Y(v)));
    ctx.lineTo(X(trend.length - 1), ht); ctx.closePath(); ctx.fillStyle = g; ctx.fill();

    ctx.beginPath();
    trend.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
    ctx.strokeStyle = '#F0A11B'; ctx.lineWidth = 2.2; ctx.lineJoin = 'round'; ctx.stroke();
  }, [trend]);

  const atRisk = score !== null && score < 70;

  return (
    <div className="page-container on">
      <div className="crumb">
        <span className="b" onClick={() => router.push('/dashboard/incidents')}>Incidents</span> /{' '}
        <span>Asset Health — {code}</span>
      </div>
      <div className="page-head">
        <div>
          <div className="row gap10">
            <h1>{code} · Asset Health</h1>
            {atRisk && <span className="badge b-crit"><span className="dot" />At risk</span>}
            {health?.recurring_failure && <span className="badge b-warn">Recurring failure</span>}
          </div>
          <div className="sub">
            {detail
              ? `${detail.asset.name} · ${detail.asset.asset_type} · commissioned ${detail.asset.commissioned_on ?? '—'}`
              : resource.loading ? 'Loading…' : 'Asset unavailable'}
          </div>
        </div>
        <select
          className="btn btn-secondary btn-sm"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        >
          {assets.map((a) => (
            <option key={a.id} value={a.id}>{a.id} · {a.name}</option>
          ))}
        </select>
      </div>

      <div className="grid g-2" style={{ gridTemplateColumns: '1.15fr 1fr', alignItems: 'start' }}>
        <div className="col gap12">
          {/* Health Score Ring */}
          <div className="card">
            <div className="card-h"><h3>Health Score</h3></div>
            <div className="card-b row gap16" style={{ justifyContent: 'center', padding: 24 }}>
              <div className="hring">
                <svg width="100" height="100" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="42" fill="none" stroke="var(--surface-3)" strokeWidth="8" />
                  <circle cx="50" cy="50" r="42" fill="none" stroke={atRisk ? '#F0A11B' : '#22B463'} strokeWidth="8"
                    strokeDasharray={`${(score ?? 0) * 2.64} ${100 * 2.64}`}
                    strokeLinecap="round"
                    style={{ transform: 'rotate(-90deg)', transformOrigin: 'center' }} />
                </svg>
                <div className="hv">
                  <div style={{ fontSize: 30, fontWeight: 800, color: atRisk ? '#F0A11B' : '#22B463' }}>
                    {score ?? '—'}
                  </div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--ink-3)' }}>/ 100</div>
                </div>
              </div>
              <div>
                <span className={`badge ${atRisk ? 'b-warn' : 'b-normal'}`}>
                  <span className="dot" />{atRisk ? 'Below threshold (70)' : 'Healthy'}
                </span>
                <div className="t-sm muted" style={{ marginTop: 8 }}>
                  {health
                    ? `Updated ${fmtDateTime(health.updated_at)}`
                    : 'No health record yet — the agent writes one after the first closed incident.'}
                </div>
              </div>
            </div>
          </div>

          {/* Metric grid */}
          <div className="grid g-4" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
            {([
              { label: 'Failures recorded', val: String(health?.failure_count ?? 0), cls: (health?.failure_count ?? 0) > 2 ? 'crit' : '' },
              { label: 'Incidents (window)', val: String(detail?.incidents.length ?? 0), cls: '' },
              { label: 'Work orders', val: String(orders.length), cls: '' },
              { label: 'Mean TTWR', val: fmtDuration(health?.mean_ttwr_minutes ?? (ttwrs.length ? ttwrs.reduce((a, b) => a + b, 0) / ttwrs.length : null)), cls: 'warn' },
              { label: 'MTBF', val: health?.mtbf_hours ? `${Math.round(health.mtbf_hours)} h` : '—', cls: 'ok' },
              { label: 'Last failure', val: fmtDateTime(health?.last_failure_at), cls: '' },
              { label: 'Last repair', val: fmtDateTime(health?.last_repair_at), cls: '' },
              { label: 'Households served', val: String(detail?.asset.households_served ?? 0), cls: 'aqua' },
            ]).map((m, i) => (
              <div key={i} className={`metric ${m.cls}`}>
                <div className="m-label">{m.label}</div>
                <div className="m-val" style={{ fontSize: 18 }}>{m.val}</div>
              </div>
            ))}
          </div>

          {/* Health Trend chart */}
          <div className="card">
            <div className="card-h">
              <h3>Health Trend</h3>
              <span className="badge b-neutral">{trend.length} points</span>
            </div>
            <div className="card-b">
              {trend.length >= 2
                ? <canvas ref={trendRef} style={{ width: '100%', height: 130, display: 'block' }} />
                : <div className="t-sm muted">Not enough history to draw a trend yet.</div>}
            </div>
          </div>
        </div>

        <div className="col gap12">
          <div className="card">
            <div className="card-h">
              <h3>Recent Incidents</h3>
              <span className="badge b-neutral">{detail?.incidents.length ?? 0}</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr><th>ID</th><th>Detected</th><th>Fault</th><th>Severity</th><th>TTWR</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {(detail?.incidents ?? []).length === 0 && (
                    <tr><td colSpan={6} className="t-sm muted" style={{ padding: 14 }}>
                      No incidents recorded against this asset.
                    </td></tr>
                  )}
                  {(detail?.incidents ?? []).map((ri) => {
                    const severity = severityFromScore(ri.severity_score);
                    const order = orders.find((o) => o.fault_event_id === ri.id);
                    return (
                      <tr key={ri.id} className="clickable" onClick={() => router.push(`/dashboard/incidents/${ri.id}`)}>
                        <td className="mono strong">{incidentRef(ri.id)}</td>
                        <td>{fmtDateTime(ri.detected_at)}</td>
                        <td className="strong">{faultLabel(ri.fault_type)}</td>
                        <td><span className={`badge b-${severity === 'crit' ? 'crit' : 'warn'}`}>{SEVERITY_LABEL[severity]}</span></td>
                        <td className="mono">{fmtDuration(ri.ttwr_minutes)}</td>
                        <td>{order ? workOrderStatusLabel(order.status) : ri.status}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {health?.recommendation && (
            <div className="callout co-warn" style={{ border: '1.5px solid #F3DDB4' }}>
              <svg width="18" height="18" style={{ color: 'var(--warn)', flex: 'none', marginTop: 1 }}><use href="#i-alert" /></svg>
              <div>
                <div style={{ fontWeight: 800, fontSize: 14, color: '#8A5300' }}>Agent Recommendation</div>
                <div className="t-md" style={{ color: '#95622A', marginTop: 5, lineHeight: 1.6 }}>
                  {health.recommendation}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function AssetsPage() {
  return (
    <Suspense fallback={<div className="page-container on"><div className="card"><div className="card-b t-md muted">Loading asset health…</div></div></div>}>
      <AssetHealthView />
    </Suspense>
  );
}
