'use client';
import { useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import SparklineChart from '@/components/telemetry/SparklineChart';
import { CHANNELS, useTelemetryStream } from '@/hooks/useTelemetryStream';
import { activeTTWR, slaStr, useIncidents } from '@/hooks/useIncidents';
import { useAgentStream } from '@/hooks/useAgentStream';
import { useBackendStatus } from '@/hooks/useBackendStatus';
import { SEVERITY_LABEL, fmtDuration, fmtNumber, incidentRef } from '@/lib/adapters';
import WaterNetworkMap from '@/components/map/WaterNetworkMap';

const TILES = [
  { key: 'flow', alarm: false, color: '#0E9FCB' },
  { key: 'up', alarm: false, color: '#F0A11B' },
  { key: 'tail', alarm: true, color: '#EF4444' },
  { key: 'oht', alarm: false, color: '#0E9FCB' },
  { key: 'kw', alarm: false, color: '#22B463' },
];

export default function DashboardPage() {
  const router = useRouter();
  const { series, formatValue, unit } = useTelemetryStream();
  const { incidents, summary, severityByAsset } = useIncidents();
  const { events } = useAgentStream();
  const backend = useBackendStatus();
  const agentLogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (agentLogRef.current) {
      agentLogRef.current.scrollTop = agentLogRef.current.scrollHeight;
    }
  }, [events]);

  const critical = summary?.incident_severity.critical ?? incidents.filter(i => i.severity === 'crit').length;
  const warning = summary?.incident_severity.warning ?? incidents.filter(i => i.severity === 'warn').length;
  const zones = Object.entries(summary?.households_by_zone ?? {});
  const householdsTotal = summary?.households_affected ?? 0;
  const areaHouseholds = summary?.service_area_households ?? 380;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Operations Dashboard</h1>
          <div className="sub">
            {summary ? `${summary.service_area_name} Service Area` : 'Vitpur Service Area'} · Ichhawar Block, Sehore
          </div>
        </div>
        <div className="row gap8">
          <span className={`badge ${backend.badgeClass}`}><span className="dot" />{backend.label}</span>
          <span className="badge b-crit"><span className="dot" />{critical} Critical</span>
          <span className="badge b-warn"><span className="dot" />{warning} Warning</span>
          <button className="btn btn-secondary btn-sm" onClick={() => router.push('/dashboard/demo')}>
            <svg width="13" height="13"><use href="#i-bolt" /></svg>
            Demo Control
          </button>
        </div>
      </div>

      {/* Two-column dashboard layout */}
      <div className="grid g-dash" style={{ gridTemplateColumns: '1fr 370px', alignItems: 'start' }}>
        {/* LEFT COLUMN */}
        <div className="col" style={{ gap: 12, minWidth: 0 }}>

          {/* A. NETWORK MAP */}
          <div className="card">
            <div className="card-h">
              <h3>A · Network Map</h3>
              <div className="row gap8">
                <span className="badge b-crit"><span className="dot" />{critical} fault{critical === 1 ? '' : 's'}</span>
                <button className="textlink" onClick={() => router.push('/dashboard/assets')}>All assets</button>
              </div>
            </div>
            <div className="card-b" style={{ padding: 0 }}>
              <WaterNetworkMap severityByAsset={severityByAsset} />
            </div>
          </div>

          {/* D. TELEMETRY */}
          <div className="card">
            <div className="card-h">
              <h3>D · Telemetry <span style={{ color: 'var(--good)', fontWeight: 600, letterSpacing: 0, textTransform: 'none' as const }}>· live</span></h3>
              <div className="row gap8">
                <span className="badge b-neutral">
                  {summary ? `${summary.sensors.trusted}/${summary.sensors.total} sensors trusted` : 'sensor feed'}
                </span>
                <button className="textlink" onClick={() => router.push('/dashboard/telemetry')}>Full telemetry</button>
              </div>
            </div>
            <div className="card-b">
              <div className="grid g-5" style={{ gridTemplateColumns: 'repeat(5, 1fr)' }}>
                {TILES.map((ch) => (
                  <div key={ch.key} className={`tel ${ch.alarm ? 'alarm' : ''}`}>
                    <div className="tl">{CHANNELS[ch.key].label.replace(/\s*\(.*\)$/, '')} ({unit(ch.key)})</div>
                    <div className="tv">{formatValue(ch.key)}</div>
                    <SparklineChart data={series[ch.key] || []} color={ch.color} />
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* C. ACTIVE INCIDENTS */}
          <div className="card">
            <div className="card-h">
              <h3>C · Active Incidents</h3>
              <div className="row gap8">
                <span className="badge b-crit"><span className="dot" />{critical} Critical</span>
                <span className="badge b-warn"><span className="dot" />{warning} Warning</span>
                <button className="textlink" onClick={() => router.push('/dashboard/incidents')}>View all</button>
              </div>
            </div>
            <div>
              {incidents.length === 0 && (
                <div className="card-b t-md muted">
                  No open incidents. The network is behaving as its baseline says it should.
                </div>
              )}
              {incidents.map((inc) => (
                <div
                  key={inc.id}
                  className={`inc ${inc.severity}`}
                  onClick={() => router.push(`/dashboard/incidents/${inc.id}`)}
                >
                  <div className="sev-ic">
                    <svg width="17" height="17"><use href={inc.icon} /></svg>
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div className="ttl">{inc.asset_id} — {inc.fault_type}</div>
                    <div className="meta">
                      <span>{inc.households_affected ? `${fmtNumber(inc.households_affected)} households` : 'No supply impact'}</span>
                      <span>·</span>
                      <span>{inc.status}</span>
                      <span>·</span>
                      <span className="mono">{incidentRef(inc.id)}</span>
                    </div>
                  </div>
                  <div>
                    <div className="row gap8" style={{ justifyContent: 'flex-end', marginBottom: 4 }}>
                      <span className={`badge b-${inc.severity === 'crit' ? 'crit' : 'warn'}`}>
                        <span className="dot" />{SEVERITY_LABEL[inc.severity]}
                      </span>
                    </div>
                    <div className={`sla ${inc.severity}`}>
                      <span className="cap">SLA</span>
                      <span>{inc.sla_remaining_seconds ? slaStr(inc.sla_remaining_seconds) : 'not dispatched'}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className="col" style={{ gap: 12, minWidth: 0 }}>

          {/* B. WATER HEALTH SUMMARY */}
          <div className="card">
            <div className="card-h">
              <h3>B · Water Health Summary</h3>
              <span className="badge b-neutral">Last 72h</span>
            </div>
            <div className="card-b">
              <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                <div className={`metric ${(summary?.water_health_score ?? 100) >= 85 ? 'ok' : 'warn'}`}>
                  <div className="m-label">Water Health Score</div>
                  <div className="m-val">{summary?.water_health_score ?? '—'}<small> /100</small></div>
                  <div className="m-sub">
                    <span className={`badge ${(summary?.water_health_score ?? 100) >= 85 ? 'b-normal' : 'b-warn'}`}>
                      {(summary?.water_health_score ?? 100) >= 85 ? 'Healthy' : 'Degraded'}
                    </span>
                  </div>
                </div>
                <div className="metric ok">
                  <div className="m-label">Sensor Trust</div>
                  <div className="m-val">{summary?.network_uptime_pct ?? '—'}<small>%</small></div>
                  <div className="m-sub">Instruments the agent may believe</div>
                </div>
                <div className="metric crit">
                  <div className="m-label">Active Incidents</div>
                  <div className="m-val">{summary?.open_incidents ?? incidents.length}</div>
                  <div className="m-sub">{critical} critical · {warning} warning</div>
                </div>
                <div className="metric aqua">
                  <div className="m-label">Open Work Orders</div>
                  <div className="m-val">{summary?.open_work_orders ?? 0}</div>
                  <div className="m-sub">{summary?.sla_breached ?? 0} past SLA</div>
                </div>
              </div>
              <div className="metric crit" style={{ marginTop: 12 }}>
                <div className="m-label">Households Affected</div>
                <div className="row between" style={{ alignItems: 'flex-end' }}>
                  <div className="m-val">{fmtNumber(householdsTotal)}</div>
                  <div className="t-xs muted" style={{ textAlign: 'right' }}>
                    {zones.length
                      ? zones.map(([zone, count]) => `${zone} ${count}`).join(' · ')
                      : 'No zone isolated'}
                  </div>
                </div>
                <div className="prog crit" style={{ marginTop: 9 }}>
                  <i style={{ width: `${Math.min(100, Math.round((householdsTotal / areaHouseholds) * 100))}%` }} />
                </div>
              </div>
            </div>
          </div>

          {/* F. TTWR */}
          <div className="ttwr">
            <div className="z">
              <div className="row between">
                <div className="eyebrow" style={{ color: '#7FB2D6' }}>Time to Water Restored</div>
                <span className="badge" style={{
                  background: summary?.active_incident_id ? 'rgba(239,68,68,.16)' : 'rgba(34,180,99,.16)',
                  borderColor: summary?.active_incident_id ? 'rgba(239,68,68,.4)' : 'rgba(34,180,99,.4)',
                  color: summary?.active_incident_id ? '#FFAFAF' : '#8FE3B4',
                }}>
                  <span className="dot" />{summary?.active_incident_id ? 'Running' : 'Idle'}
                </span>
              </div>
              <div className="big" style={{ marginTop: 10 }}>{activeTTWR(summary)}</div>
              <div className="t-xs" style={{ color: '#8FB2CC', marginTop: 6 }}>
                {summary?.active_incident_id ? (
                  <>Current incident <span className="mono">{incidentRef(summary.active_incident_id)}</span></>
                ) : (
                  'No incident is currently running'
                )}
              </div>
              <div style={{ marginTop: 14 }}>
                <div className="kv"><span>Mean TTWR (72 h)</span><b>{fmtDuration(summary?.mean_ttwr_minutes)}</b></div>
                <div className="kv"><span>Reopen rate</span><b style={{ color: '#FBBF24' }}>{Math.round((summary?.reopen_rate ?? 0) * 100)}%</b></div>
                <div className="kv"><span>Closed in window</span><b style={{ color: '#8FE3B4' }}>{summary?.closed_in_window ?? 0}</b></div>
                <div className="kv"><span>VWSC balance</span><b>{summary?.budget_remaining != null ? `₹${fmtNumber(Math.round(summary.budget_remaining))}` : '—'}</b></div>
              </div>
            </div>
          </div>

          {/* E. AGENT ACTIVITY */}
          <div className="agentbox">
            <div className="ah">
              <h3>E · Agent Activity</h3>
              <span className="badge" style={{
                background: 'rgba(63,198,232,.14)',
                borderColor: 'rgba(63,198,232,.35)',
                color: '#7FDCF5',
              }}>
                <span className="dot" />Live
              </span>
            </div>
            <div className="agent-log" ref={agentLogRef}>
              {events.map((ev, i) => (
                <div key={i} className={`aev ${ev.status}`}>
                  <span className="t">{ev.time}</span>
                  <span className="m"><i /></span>
                  <span className="x">
                    <b>{ev.message}</b>
                    {ev.tag && <span className="tagx">{ev.tag}</span>}
                  </span>
                </div>
              ))}
            </div>
            <div style={{
              padding: '9px 13px',
              borderTop: '1px solid rgba(255,255,255,.09)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}>
              <span style={{ fontSize: 11, color: '#5B84A8' }}>Decision ledger · retained 90 days</span>
              <button className="textlink" style={{ color: '#5FC8EA' }} onClick={() => router.push('/dashboard/agents')}>
                Open agent console
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
