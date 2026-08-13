'use client';
import { Suspense, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import SparklineChart from '@/components/telemetry/SparklineChart';
import { CHANNELS, useTelemetryStream } from '@/hooks/useTelemetryStream';
import { useWorkOrder, useWorkOrders } from '@/hooks/useWorkOrders';
import {
  VERIFICATION_BADGE,
  fmtDateTime,
  fmtDuration,
  incidentRef,
  toVerificationChecks,
  workOrderStatusLabel,
} from '@/lib/adapters';

function VerificationView() {
  const router = useRouter();
  const search = useSearchParams();
  const { orders } = useWorkOrders();
  const [picked, setPicked] = useState<string | null>(search.get('wo'));

  // Default to an order that is actually waiting on verification.
  const waiting = orders.find(
    (o) => o.status === 'VERIFYING' || o.status === 'RESTORATION_DETECTED',
  );
  const selected = picked ?? (waiting ?? orders[0])?.wo_code ?? null;
  const setSelected = setPicked;

  const wo = useWorkOrder(selected);
  const { series, formatValue, unit } = useTelemetryStream();

  const report = wo.report;
  const checks = useMemo(() => (report ? toVerificationChecks(report) : []), [report]);
  const pct = report ? Math.round((checks.filter((c) => c.status === 'pass').length / Math.max(1, checks.length)) * 100) : 0;
  const badge = report ? VERIFICATION_BADGE[report.outcome] : null;

  const order = wo.order;

  return (
    <div className="page-container on">
      <div className="crumb">
        <span className="b" onClick={() => router.push('/dashboard/workorders')}>{order?.wo_code ?? 'Work orders'}</span> / <span>Verification</span>
      </div>
      <div className="page-head">
        <div>
          <h1>Restoration Verification</h1>
          <div className="sub">The field says fixed. The water decides.</div>
        </div>
        <div className="row gap8">
          <select
            className="btn btn-secondary btn-sm"
            value={selected ?? ''}
            onChange={(e) => setSelected(e.target.value)}
          >
            {orders.length === 0 && <option value="">No work orders</option>}
            {orders.map((o) => (
              <option key={o.id} value={o.wo_code}>
                {o.wo_code} · {workOrderStatusLabel(o.status)}
              </option>
            ))}
          </select>
          <button
            className="btn btn-secondary btn-sm"
            disabled={!order || wo.busy === 'fieldUpdate'}
            onClick={() => wo.fieldUpdate('Fixed', 'operator console')}
          >
            <svg width="13" height="13"><use href="#i-play" /></svg>
            Report &ldquo;Fixed&rdquo;
          </button>
          <button
            className="btn btn-primary btn-sm"
            disabled={!order || wo.busy === 'verify'}
            onClick={() => wo.verify()}
          >
            <svg width="13" height="13"><use href="#i-shield" /></svg>
            {wo.busy === 'verify' ? 'Reading sensors…' : 'Run verification'}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            disabled={!order || wo.busy === 'reopen'}
            onClick={() => wo.reopen('reopened from the console')}
          >
            <svg width="13" height="13"><use href="#i-refresh" /></svg>Reopen
          </button>
        </div>
      </div>

      <div className="grid g-2" style={{ gridTemplateColumns: '1.25fr 1fr', alignItems: 'start' }}>
        <div className="card">
          <div className="card-h">
            <h3>
              {report?.outcome === 'PASSED' ? 'Verification Complete'
                : report?.outcome === 'FAILED' ? 'Verification Failed'
                  : report?.outcome === 'UNVERIFIABLE' ? 'Verification Impossible'
                    : 'Verification In Progress'}
            </h3>
            <span className={`badge ${badge?.badge ?? 'b-rest'}`}>
              <span className="dot" />{badge?.label ?? 'Watching telemetry'}
            </span>
          </div>
          <div className="card-b">
            {!report && (
              <div className="callout co-info" style={{ marginBottom: 14 }}>
                <svg width="19" height="19" style={{ color: '#0A7EA3', flex: 'none', marginTop: 1 }}><use href="#i-drop" /></svg>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 800, letterSpacing: '-.01em', color: '#0A5C79' }}>
                    {order ? workOrderStatusLabel(order.status).toUpperCase() : 'NO WORK ORDER SELECTED'}
                  </div>
                  <div className="t-md" style={{ color: '#0A7EA3', marginTop: 3, fontWeight: 600 }}>
                    Verification reads the sensors over the restoration window and closes the
                    work order only if every applicable condition holds. Run it to see the result.
                  </div>
                </div>
              </div>
            )}

            {/* Checklist — one row per condition the backend actually evaluated */}
            <div>
              {checks.map((chk) => (
                <div key={chk.key} className={`chk ${chk.status}`}>
                  <span className="ic">
                    {chk.status === 'pass' && <svg width="11" height="11"><use href="#i-chk" /></svg>}
                    {chk.status === 'fail' && <svg width="11" height="11"><use href="#i-x" /></svg>}
                  </span>
                  <span className="nm">{chk.name}</span>
                  <span className="vl">{chk.current_value} / {chk.expected_range}</span>
                </div>
              ))}
              {report && checks.length === 0 && (
                <div className="t-md muted">
                  No conditions applied to this fault class. {report.summary}
                </div>
              )}
            </div>

            {/* Progress */}
            {report && (
              <div style={{ marginTop: 16 }}>
                <div className="row between t-sm" style={{ marginBottom: 6 }}>
                  <span className="muted" style={{ fontWeight: 600 }}>Conditions held</span>
                  <span className="mono" style={{ fontWeight: 700 }}>{pct}%</span>
                </div>
                <div className={`prog ${report.outcome === 'FAILED' ? 'crit' : ''}`}>
                  <i style={{ width: `${pct}%` }} />
                </div>
              </div>
            )}

            {report?.untrusted_sensors.length ? (
              <div className="callout co-warn" style={{ marginTop: 14 }}>
                <svg width="17" height="17" style={{ color: 'var(--warn)', flex: 'none', marginTop: 1 }}><use href="#i-alert" /></svg>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 13, color: '#8A5300' }}>Untrusted instruments excluded</div>
                  <div className="t-sm" style={{ color: '#95622A', marginTop: 3 }}>
                    {report.untrusted_sensors.join(', ')}
                  </div>
                </div>
              </div>
            ) : null}

            {/* Passed */}
            {report?.outcome === 'PASSED' && (
              <div style={{ marginTop: 16 }}>
                <div style={{ border: '1.5px solid var(--good)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
                  <div style={{ background: 'var(--good)', color: '#fff', padding: '6px 13px', fontSize: 10, fontWeight: 800, letterSpacing: '.14em', textTransform: 'uppercase' as const }}>
                    Verified Restoration
                  </div>
                  <div style={{ padding: 20, background: 'var(--good-soft)', textAlign: 'center' }}>
                    <div style={{ width: 54, height: 54, margin: '0 auto', borderRadius: '50%', background: 'var(--good)', display: 'grid', placeItems: 'center', color: '#fff', boxShadow: '0 0 0 8px rgba(18,140,74,.14)' }}>
                      <svg width="28" height="28"><use href="#i-chk" /></svg>
                    </div>
                    <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.14em', textTransform: 'uppercase' as const, color: 'var(--good)', marginTop: 14 }}>
                      Time to Water Restored
                    </div>
                    <div className="mono" style={{ fontSize: 38, fontWeight: 600, color: '#0C6B39', letterSpacing: '-.02em', marginTop: 4 }}>
                      {fmtDuration(report.ttwr_minutes)}
                    </div>
                    <div className="t-sm" style={{ color: '#2C7A52', marginTop: 8 }}>
                      {order?.fault_event_id && <>Incident <b className="mono">{incidentRef(order.fault_event_id)}</b> </>}
                      closed {fmtDateTime(report.checked_at)} — closed by sensor evidence, not by claim.
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Failed / unverifiable */}
            {(report?.outcome === 'FAILED' || report?.outcome === 'UNVERIFIABLE') && (
              <div style={{ marginTop: 16 }}>
                <div style={{ border: '1.5px solid var(--crit)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
                  <div style={{ background: 'var(--crit)', color: '#fff', padding: '6px 13px', fontSize: 10, fontWeight: 800, letterSpacing: '.14em', textTransform: 'uppercase' as const }}>
                    {report.outcome === 'FAILED' ? 'Verification Failed' : 'Unverifiable'}
                  </div>
                  <div style={{ padding: 18, background: 'var(--crit-soft)' }}>
                    <div className="row gap12">
                      <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'var(--crit)', display: 'grid', placeItems: 'center', color: '#fff', flex: 'none' }}>
                        <svg width="22" height="22"><use href="#i-x" /></svg>
                      </div>
                      <div>
                        <div style={{ fontSize: 15, fontWeight: 800, color: '#8E1F1F' }}>
                          {report.outcome === 'FAILED' ? 'WORK ORDER REOPENED' : 'A HUMAN MUST INSPECT'}
                        </div>
                        <div className="t-md" style={{ color: '#9B3B3B', marginTop: 3 }}>{report.summary}</div>
                      </div>
                    </div>
                    <div className="row gap12 wrap" style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #F2C7C7' }}>
                      <div><div className="eyebrow" style={{ color: '#9B3B3B' }}>Checked at</div><div className="mono t-md" style={{ fontWeight: 700, color: '#8E1F1F' }}>{fmtDateTime(report.checked_at)}</div></div>
                      <div><div className="eyebrow" style={{ color: '#9B3B3B' }}>Window</div><div className="t-md" style={{ fontWeight: 700, color: '#8E1F1F' }}>{report.window_minutes} min</div></div>
                      <div><div className="eyebrow" style={{ color: '#9B3B3B' }}>Reopen count</div><div className="t-md" style={{ fontWeight: 700, color: '#8E1F1F' }}>{order?.reopen_count ?? 0}</div></div>
                      <div className="spacer" />
                      <button className="btn btn-danger btn-sm" onClick={() => router.push(`/dashboard/escalation?wo=${order?.wo_code ?? ''}`)}>
                        View escalation
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {report?.outcome === 'PENDING' && (
              <div className="callout co-info" style={{ marginTop: 14 }}>
                <svg width="17" height="17" style={{ color: '#0A7EA3', flex: 'none', marginTop: 1 }}><use href="#i-clock" /></svg>
                <span className="t-sm" style={{ color: '#0A5C79' }}>{report.summary}</span>
              </div>
            )}
          </div>
        </div>

        <div className="col gap12">
          <div className="card">
            <div className="card-h">
              <h3>Live Verification Telemetry</h3>
              <span className="badge b-neutral">{report ? `${report.window_minutes} min window` : 'live'}</span>
            </div>
            <div className="card-b">
              <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                <div className="tel">
                  <div className="tl">{CHANNELS.vflow.label} ({unit('vflow')})</div>
                  <div className="tv">{formatValue('vflow')}</div>
                  <SparklineChart data={series.vflow || []} color="#0E9FCB" />
                </div>
                <div className="tel">
                  <div className="tl">{CHANNELS.vtail.label} ({unit('vtail')})</div>
                  <div className="tv">{formatValue('vtail')}</div>
                  <SparklineChart data={series.vtail || []} color="#EF4444" />
                </div>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-h"><h3>Why Verification Exists</h3></div>
            <div className="card-b">
              <p className="t-md" style={{ color: 'var(--ink-2)', lineHeight: 1.65 }}>
                In conventional systems a ticket closes when a field worker says it is fixed.
                That produces a paper-complete network and a dry village.
              </p>
              <div className="divider" />
              {([
                ['Reopen count on this order', String(order?.reopen_count ?? 0), undefined],
                ['Order status', order ? workOrderStatusLabel(order.status) : '—', undefined],
                ['Last outcome', report?.outcome ?? 'not run', report?.outcome === 'FAILED' ? 'var(--crit)' : 'var(--good)'],
              ] as Array<[string, string, string | undefined]>).map(([k, v, c], i) => (
                <div key={i} className="row between" style={{ padding: '6px 0' }}>
                  <span className="t-md muted">{k}</span>
                  <b className="mono" style={c ? { color: c } : undefined}>{v}</b>
                </div>
              ))}
              <div className="callout co-neutral" style={{ marginTop: 10 }}>
                <svg width="16" height="16" style={{ color: 'var(--ink-3)', flex: 'none', marginTop: 1 }}><use href="#i-shield" /></svg>
                <span className="t-sm" style={{ color: 'var(--ink-2)' }}>
                  There is no endpoint that closes a work order. The only path to CLOSED runs
                  through this screen&apos;s verification call.
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function VerificationPage() {
  return (
    <Suspense fallback={<div className="page-container on"><div className="card"><div className="card-b t-md muted">Loading verification…</div></div></div>}>
      <VerificationView />
    </Suspense>
  );
}
