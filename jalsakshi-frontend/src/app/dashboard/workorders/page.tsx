'use client';
import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useWorkOrder, useWorkOrders } from '@/hooks/useWorkOrders';
import { slaStr } from '@/hooks/useIncidents';
import {
  fmtCurrency,
  fmtDateTime,
  incidentRef,
  roleLabel,
  workOrderStatusLabel,
} from '@/lib/adapters';

function WorkOrdersView() {
  const router = useRouter();
  const search = useSearchParams();
  const { orders, live } = useWorkOrders();
  const [picked, setPicked] = useState<string | null>(search.get('wo'));

  // Until the operator picks one, show the newest order the list returned.
  const selected = picked ?? orders[0]?.wo_code ?? null;
  const setSelected = setPicked;

  const wo = useWorkOrder(selected);
  const view = wo.view;
  const order = wo.order;

  const [message, setMessage] = useState('Fixed');

  if (!live) {
    return (
      <div className="page-container on">
        <div className="card"><div className="card-b t-md muted">
          Work orders are unavailable — the backend is not reachable.
        </div></div>
      </div>
    );
  }

  if (orders.length === 0) {
    return (
      <div className="page-container on">
        <div className="page-head">
          <div>
            <h1>Work Orders</h1>
            <div className="sub">Nothing is open. Incidents become work orders when the agent dispatches them.</div>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => router.push('/dashboard/demo')}>
            <svg width="13" height="13"><use href="#i-bolt" /></svg>Open demo control
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container on">
      <div className="crumb">
        <span className="b" onClick={() => router.push('/dashboard/incidents')}>Incidents</span> /{' '}
        <span>{order?.wo_code ?? '—'}</span>
      </div>
      <div className="page-head">
        <div>
          <div className="row gap10">
            <h1 className="mono" style={{ fontSize: 20 }}>{order?.wo_code ?? '—'}</h1>
            <span className="badge b-warn"><span className="dot" />{order ? workOrderStatusLabel(order.status) : '—'}</span>
            {order?.sla_breached && <span className="badge b-crit"><span className="dot" />SLA breached</span>}
            {order?.requires_approval && !order.approved_by && (
              <span className="badge b-warn">Awaiting VWSC approval</span>
            )}
          </div>
          <div className="sub">
            {order?.fault_event_id ? (
              <>Linked to incident <span className="mono">{incidentRef(order.fault_event_id)}</span> · {view?.fault_type}</>
            ) : 'No linked incident'}
          </div>
        </div>
        <div className="row gap8">
          <select
            className="btn btn-secondary btn-sm"
            value={selected ?? ''}
            onChange={(e) => setSelected(e.target.value)}
          >
            {orders.map((o) => (
              <option key={o.id} value={o.wo_code}>
                {o.wo_code} · {workOrderStatusLabel(o.status)}
              </option>
            ))}
          </select>
          <button
            className="btn btn-secondary btn-sm"
            disabled={!order?.fault_event_id}
            onClick={() => order?.fault_event_id && router.push(`/dashboard/incidents/${order.fault_event_id}`)}
          >
            View incident
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => router.push(`/dashboard/verification?wo=${order?.wo_code ?? ''}`)}
          >
            Verification
          </button>
        </div>
      </div>

      {/* Definition list */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="dl" style={{ borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
          {([
            ['Fault', view?.fault_type ?? '—', ''],
            ['Asset', view?.asset_id ?? '—', 'mono'],
            ['Assigned to', view?.assigned_to ?? roleLabel(order?.assigned_role), ''],
            ['Created', view?.created_at ?? '—', 'mono'],
            ['SLA deadline', view?.sla_deadline ?? '—', 'mono', 'var(--crit)'],
            ['Current state', view?.current_state ?? '—', '', 'var(--warn)'],
            ['Time remaining', wo.slaRemaining ? slaStr(wo.slaRemaining) : '—', 'mono', 'var(--crit)'],
            ['Priority', order?.priority ?? '—', '', 'var(--crit)'],
          ] as Array<[string, string, string, string?]>).map(([label, value, cls, color], i) => (
            <div key={i}>
              <dt>{label}</dt>
              <dd className={cls} style={color ? { color, fontSize: cls === 'mono' ? 12.5 : undefined } : undefined}>
                {value}
              </dd>
            </div>
          ))}
        </div>
      </div>

      {/* Work Order Timeline */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="card-h">
          <h3>Work Order Timeline</h3>
          <span className="badge b-rest">
            {order?.status === 'CLOSED' ? 'Closed on sensor evidence' : 'Restoration not yet sensor-verified'}
          </span>
        </div>
        <div className="card-b" style={{ padding: '20px 18px 16px' }}>
          <div className="wotl">
            {(view?.timeline ?? []).map((step, i) => (
              <div key={i} className={`step ${step.state}`}>
                <div className="node">
                  <svg width="14" height="14"><use href={step.icon} /></svg>
                </div>
                <div className="lbl">{step.label}</div>
                <div className="tm">{step.time}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="card-f row between wrap gap8">
          <span className="t-sm muted">
            A work order can only reach <b>Closed</b> when telemetry confirms restoration.
            Field confirmation alone moves it to <b>Verifying</b>.
          </span>
          <div className="row gap8">
            <button
              className="btn btn-secondary btn-sm"
              disabled={Boolean(wo.busy) || !order}
              onClick={() => wo.acknowledge('operator console')}
            >
              Acknowledge
            </button>
            <button
              className="btn btn-secondary btn-sm"
              disabled={Boolean(wo.busy) || !order}
              onClick={() => wo.escalate('escalated from the operations console')}
            >
              Escalate
            </button>
            <input
              className="btn btn-secondary btn-sm"
              style={{ width: 120 }}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              aria-label="Field message"
            />
            <button
              className="btn btn-primary btn-sm"
              disabled={Boolean(wo.busy) || !order}
              onClick={() => wo.fieldUpdate(message, 'operator console')}
            >
              <svg width="13" height="13"><use href="#i-play" /></svg>
              Send field update
            </button>
          </div>
        </div>
      </div>

      {/* Two-column details + notes */}
      <div className="grid g-2" style={{ gridTemplateColumns: '1fr 1fr', alignItems: 'start' }}>
        <div className="card">
          <div className="card-h"><h3>Work Order Details</h3></div>
          <div className="card-b" style={{ padding: '4px 14px' }}>
            {([
              ['Work Order ID', order?.wo_code ?? '—'],
              ['Incident ID', order?.fault_event_id ? incidentRef(order.fault_event_id) : '—'],
              ['Asset type', view?.asset_type_detail ?? '—'],
              ['Location', view?.location ?? '—'],
              ['Estimated cost', fmtCurrency(order?.estimated_cost)],
              ['Approved by', order?.approved_by ?? (order?.requires_approval ? 'Pending' : 'Not required')],
              ['Reopen count', String(order?.reopen_count ?? 0)],
              ['TTWR', order?.ttwr_minutes != null ? `${Math.round(order.ttwr_minutes)} min` : '—'],
              ['Description', view?.description ?? '—'],
            ] as Array<[string, string]>).map(([k, v], i, arr) => (
              <div key={i} className="row between" style={{ padding: '9px 0', borderBottom: i < arr.length - 1 ? '1px solid var(--line)' : 'none' }}>
                <span className="t-md muted">{k}</span>
                <b className="mono">{v}</b>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-h">
            <h3>Notes &amp; Updates</h3>
            <span className="badge b-neutral">{view?.notes.length ?? 0} entries</span>
          </div>
          <div className="card-b">
            <div className="vtl">
              {(view?.notes ?? []).map((note, i) => (
                <div key={i} className={`ev ${note.status}`}>
                  <div className="row between">
                    <b className="t-md">{note.title}</b>
                    <span className="mono t-xs muted">{note.time}</span>
                  </div>
                  <div className="t-sm muted">{note.detail}</div>
                </div>
              ))}
              {(view?.notes.length ?? 0) === 0 && (
                <div className="t-sm muted">Nothing recorded on this work order yet.</div>
              )}
            </div>
          </div>
          <div className="card-f">
            <span className="t-sm muted">
              Created {fmtDateTime(order?.created_at)} · updated {fmtDateTime(order?.updated_at)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function WorkOrdersPage() {
  return (
    <Suspense fallback={<div className="page-container on"><div className="card"><div className="card-b t-md muted">Loading work orders…</div></div></div>}>
      <WorkOrdersView />
    </Suspense>
  );
}
