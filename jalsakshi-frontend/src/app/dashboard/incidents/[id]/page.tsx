'use client';
import { useMemo } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useIncident } from '@/hooks/useIncidents';
import {
  SEVERITY_LABEL,
  faultLabel,
  fmtCurrency,
  fmtDateTime,
  fmtNumber,
  fmtSeconds,
  incidentRef,
  roleLabel,
  severityFromScore,
  workOrderStatusLabel,
} from '@/lib/adapters';

export default function IncidentDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = params?.id ?? null;

  const { incident, asset, order, decisions, anomalies, live, loading, error } = useIncident(id);

  /** The classifier's own account: the anomalies it saw, then what it concluded. */
  const trace = useMemo(() => {
    if (!incident) return [];
    const steps: Array<{ status: string; title: string; detail: string }> = [];

    const untrusted = incident.evidence?.untrusted_sensors ?? [];
    steps.push({
      status: untrusted.length ? 'warn' : 'ok',
      title: untrusted.length ? 'Sensor integrity: some instruments untrusted' : 'Sensor integrity confirmed',
      detail: untrusted.length
        ? `Excluded from the diagnosis: ${untrusted.join(', ')}.`
        : 'Every instrument feeding this diagnosis passed its health check.',
    });

    for (const anomaly of anomalies.slice(0, 6)) {
      steps.push({
        status: anomaly.severity >= 0.66 ? 'crit' : 'warn',
        title: `${anomaly.metric} deviated on ${anomaly.sensor_code ?? 'sensor'}`,
        detail: `Observed ${anomaly.observed_value?.toFixed(2) ?? '—'} against a baseline of ${
          anomaly.baseline_value?.toFixed(2) ?? '—'
        }${anomaly.z_score !== null ? ` · ${anomaly.z_score.toFixed(1)}σ` : ''}.`,
      });
    }

    const candidates = incident.evidence?.candidates ?? incident.evidence?.reasoning?.candidates ?? [];
    for (const candidate of candidates.slice(0, 3)) {
      steps.push({
        status: '',
        title: `Considered ${faultLabel(candidate.fault_type)} — score ${candidate.score.toFixed(2)}`,
        detail: [
          candidate.matched.length ? `matched ${candidate.matched.join(', ')}` : '',
          candidate.missed.length ? `missed ${candidate.missed.join(', ')}` : '',
        ].filter(Boolean).join(' · ') || 'No signature detail recorded.',
      });
    }

    steps.push({
      status: incident.fault_type === 'UNKNOWN' ? 'warn' : 'crit',
      title: `Classified: ${faultLabel(incident.fault_type)} (${Math.round(incident.confidence * 100)}%)`,
      detail: incident.evidence?.summary ?? 'No summary recorded.',
    });

    for (const entry of decisions) {
      steps.push({
        status: entry.state_change?.includes('CLOSED') ? 'ok' : 'live',
        title: entry.state_change ?? entry.tool_called ?? entry.actor,
        detail: `${fmtSeconds(entry.ts)} · ${entry.notes ?? entry.actor}`,
      });
    }

    return steps;
  }, [incident, anomalies, decisions]);

  if (!live) {
    return (
      <div className="page-container on">
        <div className="crumb">
          <span className="b" onClick={() => router.push('/dashboard/incidents')}>
            <svg width="12" height="12" style={{ verticalAlign: -2 }}><use href="#i-back" /></svg> Back to Incidents
          </span>
        </div>
        <div className="card"><div className="card-b t-md muted">
          {loading ? 'Loading incident…' : `Could not load this incident: ${error?.detail ?? 'unknown error'}`}
        </div></div>
      </div>
    );
  }

  const severity = severityFromScore(incident!.severity_score);
  const evt = incident!;

  return (
    <div className="page-container on">
      <div className="crumb">
        <span className="b" onClick={() => router.push('/dashboard/incidents')}>
          <svg width="12" height="12" style={{ verticalAlign: -2 }}><use href="#i-back" /></svg> Back to Incidents
        </span>
      </div>
      <div className="page-head">
        <div className="row gap12 wrap">
          <div>
            <div className="row gap10">
              <h1 className="mono" style={{ fontSize: 20 }}>{incidentRef(evt.id)}</h1>
              <span className={`badge b-${severity === 'crit' ? 'crit' : 'warn'}`}>
                <span className="dot" />{SEVERITY_LABEL[severity]}
              </span>
              <span className="badge b-warn">
                {order ? workOrderStatusLabel(order.status) : 'No work order yet'}
              </span>
            </div>
            <div className="sub">
              Detected {fmtDateTime(evt.detected_at)} · classifier {evt.classifier_version ?? '—'}
            </div>
          </div>
        </div>
        <div className="row gap8">
          <button
            className="btn btn-secondary btn-sm"
            disabled={!order}
            onClick={() => order && router.push(`/dashboard/workorders?wo=${order.wo_code}`)}
          >
            View work order
          </button>
          <button
            className="btn btn-secondary btn-sm"
            disabled={!order}
            onClick={() => order && router.push(`/dashboard/escalation?wo=${order.wo_code}`)}
          >
            Escalation trail
          </button>
          <button
            className="btn btn-primary btn-sm"
            disabled={!order}
            onClick={() => order && router.push(`/dashboard/verification?wo=${order.wo_code}`)}
          >
            <svg width="13" height="13"><use href="#i-shield" /></svg>Verification
          </button>
        </div>
      </div>

      {/* Definition list */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="dl" style={{ borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
          {([
            ['Asset', asset?.asset_code ?? '—', true],
            ['Fault classification', faultLabel(evt.fault_type), false],
            ['Confidence', `${Math.round(evt.confidence * 100)}%`, false, 'var(--crit)'],
            ['Detected', fmtDateTime(evt.detected_at), true],
            ['Affected households', fmtNumber(evt.households_affected), false],
            ['Anomalies', String(anomalies.length), false],
            ['Current status', order ? workOrderStatusLabel(order.status) : 'Detected', false, 'var(--warn)'],
            ['Severity', SEVERITY_LABEL[severity], false, 'var(--crit)'],
          ] as Array<[string, string, boolean, string?]>).map(([label, value, isMono, color], i) => (
            <div key={i}>
              <dt>{label}</dt>
              <dd className={isMono ? 'mono' : ''} style={color ? { color } : undefined}>{value}</dd>
            </div>
          ))}
        </div>
      </div>

      <div className="grid g-2" style={{ gridTemplateColumns: '1.35fr 1fr', alignItems: 'start' }}>
        <div className="col gap12">
          {/* Agent Reasoning Trace */}
          <div className="card">
            <div className="card-h">
              <h3>Agent Reasoning Trace</h3>
              <span className="badge b-neutral">{trace.length} steps</span>
            </div>
            <div className="card-b">
              <div className="vtl">
                {trace.map((ev, i) => (
                  <div key={i} className={`ev ${ev.status}`}>
                    <div className="t-md" style={{ fontWeight: 700 }}>{ev.title}</div>
                    <div className="t-sm muted">{ev.detail}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="card-f">
              <span className="t-sm muted">
                Every line above is read back from the decision ledger and the anomaly
                table — not regenerated by a model at page load.
              </span>
            </div>
          </div>
        </div>

        {/* Right rail */}
        <div className="col gap12">
          <div className="card">
            <div className="card-h"><h3>Action &amp; Responsibility</h3></div>
            <div className="card-b">
              <div className="callout co-info" style={{ marginBottom: 12 }}>
                <svg width="17" height="17" style={{ color: '#0A7EA3', flex: 'none', marginTop: 1 }}><use href="#i-wrench" /></svg>
                <div>
                  <div className="t-xs eyebrow" style={{ color: '#0A7EA3' }}>Recommended action</div>
                  <div style={{ fontWeight: 700, fontSize: 13.5, marginTop: 3, color: '#0A5C79' }}>
                    {order?.action_summary ?? 'No work order has been opened for this incident yet.'}
                  </div>
                </div>
              </div>
              <div className="dl" style={{ gridTemplateColumns: '1fr 1fr', border: '1px solid var(--line)', borderRadius: 'var(--r)' }}>
                {([
                  ['Assigned', order?.assigned_person ?? roleLabel(order?.assigned_role)],
                  ['Work order', order?.wo_code ?? '—'],
                  ['Estimated cost', fmtCurrency(order?.estimated_cost)],
                  ['Approval needed', order?.requires_approval ? 'Yes — above VWSC limit' : 'No'],
                  ['SLA', order?.sla_hours ? `${order.sla_hours} hours` : '—'],
                  ['SLA deadline', fmtDateTime(order?.sla_deadline)],
                ] as Array<[string, string]>).map(([k, v], i) => (
                  <div key={i}><dt>{k}</dt><dd>{v}</dd></div>
                ))}
              </div>
              <div className="row gap8" style={{ marginTop: 14 }}>
                <button className="btn btn-secondary btn-sm" style={{ flex: 1 }} onClick={() => router.push('/dashboard/agents')}>Field thread</button>
                <button
                  className="btn btn-primary btn-sm"
                  style={{ flex: 1 }}
                  disabled={!order}
                  onClick={() => order && router.push(`/dashboard/workorders?wo=${order.wo_code}`)}
                >
                  Work order
                </button>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-h"><h3>Impact Assessment</h3></div>
            <div className="card-b">
              {([
                ['Households without supply', fmtNumber(evt.households_affected)],
                ['Severity score', evt.severity_score.toFixed(2)],
                ['Asset', asset ? `${asset.name} (${asset.asset_code})` : '—'],
                ['Asset type', asset?.asset_type ?? '—'],
                ['Detection window', evt.evidence?.window_start ? `${fmtSeconds(evt.evidence.window_start)} → ${fmtSeconds(evt.evidence.window_end)}` : '—'],
              ] as Array<[string, string]>).map(([k, v], i) => (
                <div key={i} className="row between" style={{ padding: '7px 0', borderBottom: i < 4 ? '1px solid var(--line)' : 'none' }}>
                  <span className="t-md muted">{k}</span>
                  <b className="mono">{v}</b>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-h">
              <h3>Evidence</h3>
              <span className="badge b-neutral">{anomalies.length} anomalies</span>
            </div>
            <div className="card-b">
              {evt.evidence?.sensor_health_blocked && (
                <div className="callout co-warn" style={{ marginBottom: 10 }}>
                  <svg width="17" height="17" style={{ color: 'var(--warn)', flex: 'none', marginTop: 1 }}><use href="#i-alert" /></svg>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 13, color: '#8A5300' }}>Diagnosis blocked by sensor health</div>
                    <div className="t-sm" style={{ color: '#95622A', marginTop: 3 }}>
                      Every anomalous channel came from an instrument that cannot be trusted.
                      No crew is dispatched on a broken sensor&apos;s word.
                    </div>
                  </div>
                </div>
              )}
              {anomalies.slice(0, 6).map((anomaly, i) => (
                <div key={anomaly.id ?? i} className="row between" style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
                  <span className="t-sm muted">{anomaly.sensor_code} · {anomaly.metric}</span>
                  <b className="mono t-sm">{anomaly.z_score !== null ? `${anomaly.z_score.toFixed(1)}σ` : '—'}</b>
                </div>
              ))}
              {anomalies.length === 0 && <div className="t-sm muted">No anomalies attached.</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
