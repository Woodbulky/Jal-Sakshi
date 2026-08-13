'use client';
import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { slaStr, useIncidents } from '@/hooks/useIncidents';
import { SEVERITY_LABEL, fmtDuration, fmtNumber, incidentRef } from '@/lib/adapters';

type Tab = 'active' | 'verifying' | 'closed';

export default function IncidentsPage() {
  const router = useRouter();
  const { incidents, events, orders, summary, live } = useIncidents();
  const [tab, setTab] = useState<Tab>('active');

  const counts = useMemo(() => {
    const verifying = orders.filter(
      (o) => o.status === 'VERIFYING' || o.status === 'RESTORATION_DETECTED',
    ).length;
    const closed = events.filter((e) => e.status === 'RESOLVED').length;
    return { active: incidents.length, verifying, closed };
  }, [incidents.length, orders, events]);

  const rows = useMemo(() => {
    if (tab === 'active') return incidents;
    if (tab === 'verifying') {
      const verifyingEvents = new Set(
        orders
          .filter((o) => o.status === 'VERIFYING' || o.status === 'RESTORATION_DETECTED')
          .map((o) => o.fault_event_id),
      );
      return incidents.filter((i) => verifyingEvents.has(i.id));
    }
    // Closed incidents are not in the open list; show them from the raw events.
    return events
      .filter((e) => e.status === 'RESOLVED')
      .map((e) => incidents.find((i) => i.id === e.id))
      .filter((i): i is NonNullable<typeof i> => Boolean(i));
  }, [tab, incidents, orders, events]);

  return (
    <div className="page-container on">
      <div className="page-head">
        <div>
          <h1>Incidents</h1>
          <div className="sub">
            All detected faults across the {summary?.service_area_name ?? 'Vitpur'} service area
            {!live && ' · showing demo data (backend unreachable)'}
          </div>
        </div>
        <div className="row gap8">
          <div className="pilltabs">
            <button className={`pilltab ${tab === 'active' ? 'on' : ''}`} onClick={() => setTab('active')}>
              Active ({counts.active})
            </button>
            <button className={`pilltab ${tab === 'verifying' ? 'on' : ''}`} onClick={() => setTab('verifying')}>
              Verifying ({counts.verifying})
            </button>
            <button className={`pilltab ${tab === 'closed' ? 'on' : ''}`} onClick={() => setTab('closed')}>
              Closed ({counts.closed})
            </button>
          </div>
        </div>
      </div>

      <div className="grid g-4" style={{ gridTemplateColumns: 'repeat(4,1fr)', marginBottom: 12 }}>
        <div className="metric crit">
          <div className="m-label">Critical</div>
          <div className="m-val">{summary?.incident_severity.critical ?? 0}</div>
          <div className="m-sub">{summary?.sla_breached ?? 0} past SLA</div>
        </div>
        <div className="metric warn">
          <div className="m-label">Warning</div>
          <div className="m-val">{summary?.incident_severity.warning ?? 0}</div>
          <div className="m-sub">Within SLA</div>
        </div>
        <div className="metric aqua">
          <div className="m-label">Mean TTWR</div>
          <div className="m-val" style={{ fontSize: 26 }}>{fmtDuration(summary?.mean_ttwr_minutes)}</div>
          <div className="m-sub">Detection to verified restoration</div>
        </div>
        <div className="metric ok">
          <div className="m-label">Sensors trusted</div>
          <div className="m-val">
            {summary?.sensors.trusted ?? 0}<small> /{summary?.sensors.total ?? 0}</small>
          </div>
          <div className="m-sub">Guardrail 1 before any dispatch</div>
        </div>
      </div>

      <div className="card">
        <div className="card-h">
          <h3>Incident Register</h3>
          <span className="badge b-neutral">Sorted by severity</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Incident</th><th>Asset</th><th>Fault</th>
                <th>Confidence</th><th>Households</th><th>Status</th><th>SLA</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={8} className="t-md muted" style={{ padding: 18 }}>Nothing in this view.</td></tr>
              )}
              {rows.map(inc => (
                <tr key={inc.id} className="clickable" onClick={() => router.push('/dashboard/incidents/' + inc.id)}>
                  <td className="mono strong">{incidentRef(inc.id)}</td>
                  <td className="mono">{inc.asset_id}</td>
                  <td className="strong">{inc.fault_type}</td>
                  <td className="mono">{inc.classification_confidence}%</td>
                  <td className="mono">{inc.households_affected ? fmtNumber(inc.households_affected) : '—'}</td>
                  <td>{inc.status}</td>
                  <td className="mono" style={{ color: inc.severity === 'crit' ? 'var(--crit)' : 'var(--warn)', fontWeight: 600 }}>
                    {inc.sla_remaining_seconds ? slaStr(inc.sla_remaining_seconds) : '—'}
                  </td>
                  <td>
                    <span className={`badge b-${inc.severity === 'crit' ? 'crit' : 'warn'}`}>
                      {SEVERITY_LABEL[inc.severity]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
