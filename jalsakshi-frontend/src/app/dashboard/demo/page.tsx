'use client';
import { useCallback, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useSimulation } from '@/hooks/useSimulation';
import { useAgentStream } from '@/hooks/useAgentStream';
import { useIncidents } from '@/hooks/useIncidents';
import { useNetwork } from '@/hooks/useNetwork';
import { faultIcon, faultLabel, fmtSeconds, incidentRef } from '@/lib/adapters';
import type { BackendFaultType } from '@/types/backend';

/** The four faults the demo must be able to inject and diagnose. */
const DEMO_FAULTS: Array<{
  type: BackendFaultType;
  asset: string;
  signature: string;
  severity: 'crit' | 'warn';
  colorClass: string;
}> = [
  { type: 'VALVE_CLOSURE', asset: 'VLV-01', signature: 'Flow ↓ · upstream ↑ · tail ↓ · energy flat', severity: 'crit', colorClass: 'c-red' },
  { type: 'PIPELINE_BURST', asset: 'ZONE-A', signature: 'Flow ↑ · upstream ↓ · tail ↓ · energy ↑', severity: 'crit', colorClass: 'c-amb' },
  { type: 'PUMP_FAILURE', asset: 'PMP-01', signature: 'Flow ↓ · upstream ↓ · energy → 0', severity: 'crit', colorClass: 'c-org' },
  { type: 'POWER_OUTAGE', asset: 'PMP-01', signature: 'All channels → null · gateway heartbeat lost', severity: 'warn', colorClass: 'c-slate' },
];

type Stage = 'pending' | 'now' | 'done';

const STAGE_LABELS = ['Injected', 'Telemetry Impact', 'Detecting', 'Classifying', 'Dispatching'];

export default function DemoControlPage() {
  const router = useRouter();
  const sim = useSimulation();
  const agent = useAgentStream();
  const { incidents } = useIncidents({ intervalMs: 5_000 });
  const { assets } = useNetwork({ intervalMs: 15_000 });

  const [stages, setStages] = useState<Stage[]>(['pending', 'pending', 'pending', 'pending', 'pending']);
  const [statusText, setStatusText] = useState('Ready for fault injection');

  /** Asset codes the seed actually has — a fault cannot be injected elsewhere. */
  const knownAssets = useMemo(() => new Set(assets.map((a) => a.id)), [assets]);

  const setStage = (index: number, state: Stage) =>
    setStages((prev) => prev.map((s, i) => (i === index ? state : i < index ? 'done' : s)));

  /**
   * Run the whole loop against the real backend:
   * inject → tick the simulator → detect → let the agent classify and dispatch.
   * Nothing here tells the agent which fault was injected.
   */
  const inject = useCallback(
    async (faultType: BackendFaultType, assetCode: string) => {
      setStages(['now', 'pending', 'pending', 'pending', 'pending']);
      setStatusText(`Injecting ${faultLabel(faultType)} at ${assetCode} …`);

      // The backend resolves an asset code or a UUID; codes read better here.
      const injection = await sim.inject(faultType, assetCode);
      if (!injection) {
        setStatusText(`Injection failed: ${sim.lastError ?? 'the backend refused it'}`);
        setStages(['pending', 'pending', 'pending', 'pending', 'pending']);
        return;
      }

      setStage(0, 'done');
      setStage(1, 'now');
      setStatusText('Fault active — advancing the simulator so telemetry carries it …');
      await sim.tick();
      await sim.tick();

      setStage(1, 'done');
      setStage(2, 'now');
      setStatusText('Scoring the current window against the learned baseline …');
      const run = await sim.detect();

      setStage(2, 'done');
      setStage(3, 'now');
      const verdict = run?.classification;
      setStatusText(
        verdict
          ? `Classifier says ${faultLabel(verdict.fault_type)} at ${Math.round(verdict.confidence * 100)}% confidence.`
          : 'Detection ran; no fault event was raised from this window.',
      );

      setStage(3, 'done');
      setStage(4, 'now');
      const pass = await agent.run();
      setStage(4, 'done');
      setStatusText(
        pass?.halted
          ? `Agent halted: ${pass.halted}`
          : pass?.work_order
            ? `Work order ${pass.work_order.wo_code} dispatched.`
            : 'Agent pass complete — nothing further to do this tick.',
      );
    },
    [sim, agent],
  );

  const reset = useCallback(async () => {
    await sim.clearAll();
    setStages(['pending', 'pending', 'pending', 'pending', 'pending']);
    setStatusText('All injections cleared. Telemetry will recover; work orders stay open.');
  }, [sim]);

  const busy = Boolean(sim.busy) || agent.running;

  return (
    <div className="page-container on">
      <div className="page-head">
        <div>
          <h1>Demo Control</h1>
          <div className="sub">Inject faults, observe detection latency, and test the full agentic pipeline</div>
        </div>
        <div className="row gap8">
          <span className={`badge ${sim.running ? 'b-normal' : 'b-warn'}`}>
            <span className="dot" />{sim.running ? 'Simulator running' : 'Simulator paused'}
          </span>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => (sim.running ? sim.pause() : sim.start())}>
            <svg width="13" height="13"><use href={sim.running ? '#i-clock' : '#i-play'} /></svg>
            {sim.running ? 'Pause' : 'Start'}
          </button>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => sim.backfill(48)}>
            Backfill 48 h
          </button>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={reset}>
            <svg width="13" height="13"><use href="#i-refresh" /></svg>Clear faults
          </button>
        </div>
      </div>

      {sim.lastError && (
        <div className="callout co-warn" style={{ marginBottom: 12 }}>
          <svg width="17" height="17" style={{ color: 'var(--warn)', flex: 'none', marginTop: 1 }}><use href="#i-alert" /></svg>
          <span className="t-sm" style={{ color: '#95622A' }}>{sim.lastError}</span>
        </div>
      )}

      <div className="grid g-4" style={{ gridTemplateColumns: 'repeat(4,1fr)', marginBottom: 12 }}>
        {DEMO_FAULTS.map((f) => (
          <div
            key={f.type}
            className={`fi ${f.colorClass} ${busy ? 'busy' : ''}`}
            title={knownAssets.has(f.asset) ? undefined : `${f.asset} is not in the current seed`}
            onClick={() => !busy && inject(f.type, f.asset)}
          >
            <div className="fic">
              <svg width="22" height="22"><use href={faultIcon(f.type)} /></svg>
            </div>
            <div className="fn">{faultLabel(f.type)}</div>
            <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>{f.asset}</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="card-h">
          <h3>Event Progress</h3>
          <span className={`badge ${busy ? 'b-warn' : 'b-neutral'}`}>
            <span className="dot" />{busy ? 'Working' : 'Idle'}
          </span>
        </div>
        <div className="card-b" style={{ padding: '20px 18px' }}>
          <div className="wotl" style={{ marginBottom: 16 }}>
            {STAGE_LABELS.map((label, i) => (
              <div key={i} className={`step ${stages[i]}`}>
                <div className="node">
                  <svg width="13" height="13">
                    <use href={stages[i] === 'done' ? '#i-chk' : stages[i] === 'now' ? '#i-bolt' : '#i-clock'} />
                  </svg>
                </div>
                <div className="lbl">{label}</div>
                <div className="tm" style={{ fontSize: 9.5, marginTop: 3, fontWeight: 600, color: stages[i] === 'now' ? 'var(--warn)' : 'var(--ink-3)' }}>
                  {stages[i] === 'done' ? 'Completed' : stages[i] === 'now' ? 'In Progress' : 'Pending'}
                </div>
              </div>
            ))}
          </div>
          <div className="t-md muted" style={{ textAlign: 'center' }}>{statusText}</div>
        </div>
      </div>

      <div className="grid g-2" style={{ gridTemplateColumns: '1fr 1fr', alignItems: 'start' }}>
        <div className="card">
          <div className="card-h">
            <h3>Active Injections</h3>
            <span className="badge b-neutral">Ground truth · operator only</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className="tbl">
              <thead>
                <tr><th>Fault</th><th>Started</th><th>State</th><th></th></tr>
              </thead>
              <tbody>
                {sim.injections.length === 0 && (
                  <tr><td colSpan={4} className="t-sm muted" style={{ padding: 14 }}>Nothing injected.</td></tr>
                )}
                {sim.injections.map((inj) => (
                  <tr key={inj.id}>
                    <td className="strong">{faultLabel(inj.fault_type)}</td>
                    <td className="mono">{fmtSeconds(inj.started_at)}</td>
                    <td>{inj.is_active ? 'Active' : 'Cleared'}</td>
                    <td>
                      <button className="textlink" disabled={busy} onClick={() => sim.clear(inj.id)}>
                        Simulate repair
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card-f">
            <span className="t-sm muted">
              Clearing a fault only makes the telemetry recover. The work order still has to
              pass verification before it can close.
            </span>
          </div>
        </div>

        <div className="card">
          <div className="card-h">
            <h3>What the Agent Concluded</h3>
            <span className="badge b-neutral">Independent of the table on the left</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className="tbl">
              <thead>
                <tr><th>Incident</th><th>Asset</th><th>Diagnosis</th><th>Confidence</th></tr>
              </thead>
              <tbody>
                {incidents.length === 0 && (
                  <tr><td colSpan={4} className="t-sm muted" style={{ padding: 14 }}>No incidents raised.</td></tr>
                )}
                {incidents.map((inc) => (
                  <tr key={inc.id} className="clickable" onClick={() => router.push(`/dashboard/incidents/${inc.id}`)}>
                    <td className="mono">{incidentRef(inc.id)}</td>
                    <td className="mono">{inc.asset_id}</td>
                    <td className="strong">{inc.fault_type}</td>
                    <td className="mono">{inc.classification_confidence}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card-f">
            <span className="t-sm muted">
              The classifier never reads the injection table. Agreement between these two
              panels is the demo&apos;s whole claim.
            </span>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-h">
          <h3>Simulation Parameters</h3>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => agent.run()}>
            <svg width="13" height="13"><use href="#i-agent" /></svg>Run agent pass
          </button>
        </div>
        <div className="card-b" style={{ padding: '4px 14px' }}>
          {([
            ['Tick interval', sim.status ? `${sim.status.tick_seconds}s` : '—'],
            ['Time scale', sim.status ? `${sim.status.time_scale}× hydraulic` : '—'],
            ['Sensors', sim.status ? String(sim.status.sensor_count) : '—'],
            ['Last tick', fmtSeconds(sim.status?.last_tick_at)],
            ['Readings written', sim.status ? String(sim.status.readings_written) : '—'],
          ] as Array<[string, string]>).map(([k, v], i, arr) => (
            <div key={i} className="row between" style={{ padding: '8px 0', borderBottom: i < arr.length - 1 ? '1px solid var(--line)' : 'none' }}>
              <span className="t-md muted">{k}</span>
              <b className="mono">{v}</b>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
