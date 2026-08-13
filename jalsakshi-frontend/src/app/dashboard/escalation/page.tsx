'use client';
import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useWorkOrder, useWorkOrders } from '@/hooks/useWorkOrders';
import { useNow } from '@/hooks/useNow';
import { fmtDuration, incidentRef, workOrderStatusLabel } from '@/lib/adapters';

function EscalationView() {
  const router = useRouter();
  const search = useSearchParams();
  const { orders } = useWorkOrders();
  const [picked, setPicked] = useState<string | null>(search.get('wo'));

  // Default to an order that has actually breached its SLA.
  const breached = orders.find((o) => o.sla_breached);
  const selected = picked ?? (breached ?? orders[0])?.wo_code ?? null;
  const setSelected = setPicked;

  const wo = useWorkOrder(selected);
  const now = useNow(30_000);
  const entries = wo.escalations;
  const order = wo.order;
  const current = entries.length ? entries[entries.length - 1].level : 0;

  const minutesSinceCreated = order?.created_at
    ? (now - new Date(order.created_at).getTime()) / 60000
    : null;

  return (
    <div className="page-container on">
      <div className="crumb">
        <span
          className="b"
          onClick={() => order?.fault_event_id && router.push(`/dashboard/incidents/${order.fault_event_id}`)}
        >
          {order?.fault_event_id ? incidentRef(order.fault_event_id) : 'Incident'}
        </span> / <span>Escalation Trail</span>
      </div>
      <div className="page-head">
        <div>
          <h1>Escalation Trail</h1>
          <div className="sub">
            {order
              ? `Auto-escalation ladder for ${order.wo_code} · ${workOrderStatusLabel(order.status)}`
              : 'No work order selected'}
          </div>
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
            disabled={!order || Boolean(wo.busy)}
            onClick={() => wo.escalate('escalated from the escalation console')}
          >
            Escalate one level
          </button>
        </div>
      </div>

      <div className="grid g-4" style={{ gridTemplateColumns: 'repeat(4,1fr)', marginBottom: 12 }}>
        {[
          { label: 'Current Level', val: current ? `L${current}` : '—', cls: current >= 3 ? 'crit' : 'warn' },
          { label: 'Time Since Detection', val: fmtDuration(minutesSinceCreated), cls: 'warn' },
          { label: 'SLA Breached', val: order?.sla_breached ? 'Yes' : 'No', cls: order?.sla_breached ? 'crit' : 'ok' },
          { label: 'Escalations Raised', val: String(entries.length), cls: 'aqua' },
        ].map((m, i) => (
          <div key={i} className={`metric ${m.cls}`}>
            <div className="m-label">{m.label}</div>
            <div className="m-val">{m.val}</div>
          </div>
        ))}
      </div>

      <div className="grid g-2" style={{ gridTemplateColumns: '1.15fr 1fr', alignItems: 'start' }}>
        <div>
          <div className="card-h" style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 'var(--r-md) var(--r-md) 0 0' }}>
            <h3>Escalation Ladder</h3>
            <span className="badge b-neutral">Policy: auto-escalate on SLA breach</span>
          </div>
          <div style={{ padding: 16, background: 'var(--surface)', border: '1px solid var(--line)', borderTop: 0, borderRadius: '0 0 var(--r-md) var(--r-md)' }}>
            {entries.length === 0 && (
              <div className="t-md muted">
                Nothing has been escalated on this work order. The ladder stays empty while
                the SLA holds.
              </div>
            )}
            {entries.map((esc, i) => (
              <div key={i} className={`esc l${esc.level} ${esc.is_pending ? 'pend' : ''}`}>
                <div className="lvl">L{esc.level}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="row between gap12 wrap">
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--ink)' }}>Level {esc.level} · {esc.role}</div>
                      <div className="t-sm muted" style={{ marginTop: 2 }}>{esc.entity}</div>
                    </div>
                    <div className="row gap8">
                      <span className={`badge ${esc.badge_type}`}>
                        <span className="dot" />{esc.is_active ? 'Active' : esc.is_pending ? 'Pending' : 'Completed'}
                      </span>
                    </div>
                  </div>
                  <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 10 }}>
                    {[
                      ['Triggered', esc.time], ['Reason', esc.reason],
                      ['SLA breach', esc.sla_breach], ['Evidence', esc.evidence],
                      ['Notification', esc.notification_status],
                    ].map(([k, v], j) => (
                      <div key={j} style={{ padding: '5px 0' }}>
                        <div className="eyebrow" style={{ fontSize: 9.5 }}>{k}</div>
                        <div className="t-sm" style={{ fontWeight: 600, marginTop: 2 }}>{v}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="col gap12">
          <div className="card">
            <div className="card-h"><h3>Escalation Policy</h3></div>
            <div style={{ overflowX: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr><th>Level</th><th>Role</th><th>Trigger</th><th>SLA</th></tr>
                </thead>
                <tbody>
                  {[
                    ['L1', 'Assigned crew', 'Detection', '4 h'],
                    ['L2', 'VWSC Secretary', 'L1 SLA breach', '2 h'],
                    ['L3', 'Block Junior Engineer', 'L2 SLA breach or verification fail', '4 h'],
                    ['L4', 'District Authority', 'Critical > 6 h + vulnerable facility', '—'],
                  ].map((r, i) => (
                    <tr key={i}><td className="strong">{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td className="mono">{r[3]}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card-h">
              <h3>Decision Ledger</h3>
              <span className="badge b-neutral">{wo.decisions.length} entries</span>
            </div>
            <div className="card-b">
              {wo.decisions.slice(-8).map((entry, i) => (
                <div key={entry.id ?? i} className="evi" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                  <svg width="14" height="14" style={{ color: 'var(--aqua)', flex: 'none' }}><use href="#i-agent" /></svg>
                  <div>
                    <div className="t-md" style={{ fontWeight: 700 }}>
                      {entry.state_change ?? entry.tool_called ?? entry.actor}
                    </div>
                    <div className="t-xs muted">{entry.notes ?? entry.actor}</div>
                  </div>
                </div>
              ))}
              {wo.decisions.length === 0 && (
                <div className="t-sm muted">No ledger entries for this work order yet.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function EscalationPage() {
  return (
    <Suspense fallback={<div className="page-container on"><div className="card"><div className="card-b t-md muted">Loading escalations…</div></div></div>}>
      <EscalationView />
    </Suspense>
  );
}
