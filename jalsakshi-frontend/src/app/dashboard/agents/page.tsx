'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useAgentStream } from '@/hooks/useAgentStream';
import { useWorkOrder, useWorkOrders } from '@/hooks/useWorkOrders';
import { useApiResource } from '@/hooks/useApiResource';
import { getRoster } from '@/lib/api/endpoints';
import {
  fmtClock,
  fmtCurrency,
  fmtDateTime,
  roleLabel,
  workOrderStatusLabel,
} from '@/lib/adapters';

export default function AgentsPage() {
  const { events, run, running, lastRun, live } = useAgentStream();
  const { orders } = useWorkOrders();
  const [picked, setPicked] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  // Until the operator picks one, show the newest work order's thread.
  const selected = picked ?? orders[0]?.wo_code ?? null;
  const setSelected = setPicked;

  const wo = useWorkOrder(selected);
  const roster = useApiResource((signal) => getRoster({ signal }), {});

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events]);

  const assignment = wo.detail?.assignments[wo.detail.assignments.length - 1] ?? null;
  const order = wo.order;

  /** The Telegram thread, reconstructed from assignments and the ledger. */
  const thread = useMemo(() => {
    const items: Array<{ kind: 'in' | 'out' | 'sys'; text: string; time: string }> = [];
    for (const a of wo.detail?.assignments ?? []) {
      items.push({
        kind: 'sys',
        text: `Work order assigned to ${a.assignee_name ?? roleLabel(a.assignee_role)}`,
        time: fmtClock(a.assigned_at),
      });
      if (a.acknowledged_at) {
        items.push({ kind: 'in', text: 'Acknowledged. On my way.', time: fmtClock(a.acknowledged_at) });
      }
    }
    for (const entry of wo.decisions) {
      if (!entry.notes && !entry.state_change) continue;
      items.push({
        kind: entry.actor === 'FIELD' ? 'in' : 'out',
        text: entry.notes ?? entry.state_change ?? '',
        time: fmtClock(entry.ts),
      });
    }
    return items;
  }, [wo.detail, wo.decisions]);

  return (
    <div className="page-container on">
      <div className="page-head">
        <div>
          <h1>Agent &amp; Communications</h1>
          <div className="sub">
            Field communication threads and the decision ledger
            {!live && ' · backend unreachable, showing the scripted narration'}
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
          <button className="btn btn-primary btn-sm" disabled={running} onClick={() => run()}>
            <svg width="13" height="13"><use href="#i-agent" /></svg>
            {running ? 'Running…' : 'Run agent pass'}
          </button>
        </div>
      </div>

      {lastRun?.halted && (
        <div className="callout co-warn" style={{ marginBottom: 12 }}>
          <svg width="17" height="17" style={{ color: 'var(--warn)', flex: 'none', marginTop: 1 }}><use href="#i-alert" /></svg>
          <div>
            <div style={{ fontWeight: 700, fontSize: 13, color: '#8A5300' }}>Agent is waiting on a human</div>
            <div className="t-sm" style={{ color: '#95622A', marginTop: 3 }}>{lastRun.halted}</div>
          </div>
        </div>
      )}

      <div className="grid g-2" style={{ gridTemplateColumns: '1fr 1.15fr', alignItems: 'start' }}>
        {/* Telegram thread */}
        <div className="card">
          <div className="card-h">
            <h3>Field Thread · Telegram</h3>
            <span className="badge b-neutral">{assignment?.telegram_chat_id ?? 'no chat bound'}</span>
          </div>
          <div className="card-b" style={{ display: 'flex', justifyContent: 'center' }}>
            <div className="tg-card">
              <div className="tg-h">
                <div className="row gap8">
                  <svg width="16" height="16"><use href="#i-tg" /></svg>
                  <span style={{ fontWeight: 700, fontSize: 13 }}>JAL-SAKSHI Bot</span>
                </div>
                <span className="badge" style={{ background: 'rgba(255,255,255,.12)', color: '#C7DCEA', borderColor: 'rgba(255,255,255,.18)' }}>
                  <span className="dot" />{order ? workOrderStatusLabel(order.status) : 'Idle'}
                </span>
              </div>
              <div className="tg-b" style={{ padding: '8px 13px 13px' }}>
                <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 4, color: '#C62828' }}>⚠️ Work Order {order?.wo_code ?? '—'}</div>
                {([
                  ['Asset', wo.view?.asset_id ?? '—'],
                  ['Fault', wo.view?.fault_type ?? '—'],
                  ['Assigned', order?.assigned_person ?? roleLabel(order?.assigned_role)],
                  ['Priority', order?.priority ?? '—'],
                  ['SLA', order?.sla_deadline ? `by ${fmtDateTime(order.sla_deadline)}` : '—'],
                  ['Cost est.', fmtCurrency(order?.estimated_cost)],
                ] as Array<[string, string]>).map(([k, v], i) => (
                  <div key={i} className="tg-row"><span className="k">{k}</span><span className="v">{v}</span></div>
                ))}
              </div>
              <div className="tg-f">
                <span style={{ fontSize: 11, color: 'var(--good)', fontWeight: 700 }}>
                  {order?.acknowledged_at ? `✓ Acknowledged ${fmtClock(order.acknowledged_at)}` : 'Awaiting acknowledgement'}
                </span>
                <div className="row gap6">
                  <button
                    className="btn btn-sm"
                    style={{ background: 'var(--good)', borderColor: 'var(--good)', padding: '4px 10px', fontSize: 11 }}
                    disabled={!order || Boolean(wo.busy)}
                    onClick={() => wo.acknowledge('field crew')}
                  >
                    Accept
                  </button>
                  <button
                    className="btn btn-sm btn-secondary"
                    style={{ padding: '4px 10px', fontSize: 11 }}
                    disabled={!order || Boolean(wo.busy)}
                    onClick={() => wo.escalate('no response on the field thread')}
                  >
                    Escalate
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Thread, from assignments and the ledger */}
          <div className="card-b" style={{ borderTop: '1px solid var(--line)', padding: '14px 14px 8px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {thread.length === 0 && (
                <div className="t-sm muted" style={{ textAlign: 'center' }}>
                  Nothing has been said on this thread yet.
                </div>
              )}
              {thread.map((item, i) => (
                <div
                  key={i}
                  className={`bubble ${item.kind === 'in' ? 'bub-in' : item.kind === 'out' ? 'bub-out' : 'bub-sys'}`}
                  style={item.kind === 'sys' ? { alignSelf: 'center', textAlign: 'center', fontSize: 11, maxWidth: '80%' } : undefined}
                >
                  <div style={{ fontSize: 12 }}>{item.text}</div>
                  <div style={{ fontSize: 10, color: item.kind === 'out' ? '#0A5C79' : 'var(--ink-3)', marginTop: 4 }}>
                    {item.time}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="card-f">
            <span className="t-sm muted">
              Outbound messages go through n8n to Telegram. An inbound &ldquo;Fixed&rdquo; starts
              verification — it cannot close the order.
            </span>
          </div>
        </div>

        {/* Agent decision log */}
        <div className="col gap12">
          <div className="agentbox" style={{ height: 'auto' }}>
            <div className="ah">
              <h3>Agent Decision Log</h3>
              <span className="badge" style={{ background: 'rgba(63,198,232,.14)', borderColor: 'rgba(63,198,232,.35)', color: '#7FDCF5' }}>
                <span className="dot" />{live ? 'Live' : 'Demo'}
              </span>
            </div>
            <div className="agent-log" ref={logRef} style={{ maxHeight: 460 }}>
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
            <div style={{ padding: '9px 13px', borderTop: '1px solid rgba(255,255,255,.09)' }}>
              <span style={{ fontSize: 11, color: '#5B84A8' }}>
                Read from the decision ledger · retained for audit
              </span>
            </div>
          </div>

          <div className="card">
            <div className="card-h">
              <h3>Roster</h3>
              <span className="badge b-neutral">{roster.data?.length ?? 0} people</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr><th>Name</th><th>Role</th><th>Contact</th><th>Available</th></tr>
                </thead>
                <tbody>
                  {(roster.data ?? []).map((member) => (
                    <tr key={member.name}>
                      <td className="strong">{member.name}</td>
                      <td>{roleLabel(member.role)}</td>
                      <td className="mono t-sm">{member.phone ?? '—'}</td>
                      <td>
                        <span className={`badge b-${member.available ? 'normal' : 'off'}`}>
                          <span className="dot" />{member.available ? 'Yes' : 'No'}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {(roster.data ?? []).length === 0 && (
                    <tr><td colSpan={4} className="t-sm muted" style={{ padding: 14 }}>Roster unavailable.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
