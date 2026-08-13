'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import ParticleField from '@/components/canvas/ParticleField';
import { useApiResource } from '@/hooks/useApiResource';
import { getNetwork, listServiceAreas } from '@/lib/api/endpoints';
import { fmtNumber } from '@/lib/adapters';

export default function ServiceAreaPage() {
  const router = useRouter();
  const [demoSelected, setDemoSelected] = useState(false);

  const areas = useApiResource((signal) => listServiceAreas({ signal }), {});
  const network = useApiResource((signal) => getNetwork(undefined, { signal }), {});

  const area = areas.data?.[0] ?? null;
  const zones = (network.data?.nodes ?? []).filter((n) => n.asset_type === 'ZONE').length;

  return (
    <div className="area-grid">
      {/* Left: Dark art panel */}
      <div className="area-art">
        <ParticleField count={44} linkDistance={130} />
        <div className="z">
          <div className="wordmark" style={{ marginBottom: 12 }}>
            <div className="logo" style={{
              background: 'linear-gradient(140deg, #1583CE, #0E9FCB)',
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
            }}>
              <svg width="16" height="16" style={{ color: '#fff' }}>
                <use href="#i-drop" />
              </svg>
            </div>
            JAL-SAKSHI
          </div>
          <div style={{
            fontSize: 'clamp(28px, 4vw, 42px)',
            fontWeight: 800,
            letterSpacing: '-.03em',
            lineHeight: 1.15,
            color: '#fff',
            marginTop: 24,
          }}>
            Select your<br />service area
          </div>
          <p style={{ fontSize: 14, color: '#8FB2CC', marginTop: 14, maxWidth: 380, lineHeight: 1.6 }}>
            Choose a Jal Jeevan Mission service area to begin monitoring. Each area includes its
            full asset network, telemetry, and agent activity.
          </p>
        </div>
        <div className="z">
          <div className="grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, maxWidth: 340 }}>
            {([
              ['Assets', network.data ? String(network.data.nodes.length) : '—'],
              ['Zones', network.data ? String(zones) : '—'],
              ['Households', area?.households != null ? fmtNumber(area.households) : '—'],
            ] as Array<[string, string]>).map(([label, value]) => (
              <div key={label} style={{ textAlign: 'center' }}>
                <div className="mono" style={{ fontSize: 24, fontWeight: 700, color: '#4FD3F2' }}>{value}</div>
                <div style={{ fontSize: 10, color: '#7FA6C2', fontWeight: 600, letterSpacing: '.1em', textTransform: 'uppercase' as const, marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right: Form panel */}
      <div className="area-form">
        <div className="form-inner">
          <div style={{ marginBottom: 24 }}>
            <h1 style={{ fontSize: 22, letterSpacing: '-.015em' }}>Service Area</h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', marginTop: 5 }}>
              Select a state, district, block and village to load its water network.
            </p>
          </div>

          <div className="field">
            <label>State</label>
            <select className="sel" defaultValue="mp">
              <option value="">Select state…</option>
              <option value="mp">Madhya Pradesh</option>
            </select>
          </div>
          <div className="field">
            <label>District</label>
            <select className="sel" defaultValue="sehore">
              <option value="">Select district…</option>
              <option value="sehore">Sehore</option>
            </select>
          </div>
          <div className="field">
            <label>Block</label>
            <select className="sel" defaultValue="ichhawar">
              <option value="">Select block…</option>
              <option value="ichhawar">Ichhawar</option>
            </select>
          </div>
          <div className="field">
            <label>Village / Habitation</label>
            <select className="sel" defaultValue={area?.code ?? 'demo-vitpur'}>
              {(areas.data ?? []).map((a) => (
                <option key={a.id} value={a.code}>
                  {a.name}{a.is_demo ? ' (Demo)' : ''}
                </option>
              ))}
              {!areas.data && <option value="demo-vitpur">Vitpur (Demo)</option>}
            </select>
          </div>

          {/* Demo card */}
          <div
            className={`demo-card ${demoSelected ? 'on' : ''}`}
            onClick={() => setDemoSelected(!demoSelected)}
          >
            <div className="rd" />
            <div>
              <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--ink)' }}>
                {area?.name ?? 'Vitpur'} · Demo Environment
              </div>
              <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4, lineHeight: 1.5 }}>
                {network.data
                  ? `${network.data.nodes.length} assets, ${network.data.sensors.length} sensors and a live simulator you drive from Demo Control. Notifications are sandboxed.`
                  : 'A fictional single-village piped supply scheme. Notifications are sandboxed.'}
              </div>
              <div className="row gap6" style={{ marginTop: 8 }}>
                <span className="badge b-warn"><span className="dot" />Demo mode</span>
                <span className="badge b-neutral">Sandbox</span>
              </div>
            </div>
          </div>

          <button
            className="btn btn-primary btn-block btn-lg"
            onClick={() => router.push('/dashboard')}
            style={{ marginTop: 4 }}
          >
            <svg width="15" height="15"><use href="#i-drop" /></svg>
            Continue to Console
          </button>

          <div style={{
            marginTop: 20,
            textAlign: 'center',
            fontSize: 11.5,
            color: 'var(--ink-3)',
          }}>
            Using demo data from Vitpur, Ichhawar Block, Sehore District
          </div>
        </div>
      </div>
    </div>
  );
}
