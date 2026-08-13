'use client';

export default function DesignSystemPage() {
  return (
    <div className="page-container on">
      <div className="page-head">
        <div>
          <h1>Design System</h1>
          <div className="sub">JAL-SAKSHI component library and design tokens</div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12 }}>
        {/* Colors */}
        <div className="card">
          <div className="card-h"><h3>Color Tokens</h3></div>
          <div className="card-b">
            <div className="grid" style={{ gridTemplateColumns: 'repeat(4,1fr)', gap: 6 }}>
              {[
                { name: 'Navy 950', bg: 'var(--navy-950)' }, { name: 'Navy 900', bg: 'var(--navy-900)' },
                { name: 'Navy 800', bg: 'var(--navy-800)' }, { name: 'Navy 700', bg: 'var(--navy-700)' },
                { name: 'Aqua', bg: 'var(--aqua)' }, { name: 'Good', bg: 'var(--good-2)' },
                { name: 'Warning', bg: 'var(--warn-2)' }, { name: 'Critical', bg: 'var(--crit-2)' },
              ].map(c => (
                <div key={c.name} style={{ textAlign: 'center' }}>
                  <div style={{ width: '100%', height: 36, background: c.bg, borderRadius: 'var(--r-sm)', marginBottom: 4 }} />
                  <div className="t-xs muted">{c.name}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Buttons */}
        <div className="card">
          <div className="card-h"><h3>Buttons</h3></div>
          <div className="card-b" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <button className="btn btn-primary">Primary</button>
            <button className="btn btn-secondary">Secondary</button>
            <button className="btn btn-ghost">Ghost</button>
            <button className="btn btn-danger">Danger</button>
            <button className="btn btn-inv" style={{ background: 'var(--navy-900)' }}>Inverted</button>
            <button className="btn btn-sm btn-primary">Small</button>
            <button className="btn btn-lg btn-primary">Large</button>
            <button className="btn btn-primary" disabled>Disabled</button>
          </div>
        </div>

        {/* Badges */}
        <div className="card">
          <div className="card-h"><h3>Status Badges</h3></div>
          <div className="card-b" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <span className="badge b-normal"><span className="dot" />Normal</span>
            <span className="badge b-warn"><span className="dot" />Warning</span>
            <span className="badge b-crit"><span className="dot" />Critical</span>
            <span className="badge b-rest"><span className="dot" />Restoring</span>
            <span className="badge b-off"><span className="dot" />Offline</span>
            <span className="badge b-neutral">Neutral</span>
          </div>
        </div>

        {/* Metrics */}
        <div className="card">
          <div className="card-h"><h3>Metric Cards</h3></div>
          <div className="card-b">
            <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <div className="metric ok">
                <div className="m-label">Uptime</div><div className="m-val">99.2<small>%</small></div>
                <div className="m-sub">Last 30 days</div>
              </div>
              <div className="metric crit">
                <div className="m-label">Critical</div><div className="m-val">2</div>
                <div className="m-sub">Needs attention</div>
              </div>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="card">
          <div className="card-h"><h3>Tabs</h3></div>
          <div className="card-b">
            <div className="pilltabs" style={{ marginBottom: 12 }}>
              <button className="pilltab on">Active</button>
              <button className="pilltab">History</button>
              <button className="pilltab">Config</button>
            </div>
            <div className="tabs">
              <button className="tab on">Overview</button>
              <button className="tab">Details</button>
              <button className="tab">Audit Log</button>
            </div>
          </div>
        </div>

        {/* Timeline */}
        <div className="card">
          <div className="card-h"><h3>Timeline Component</h3></div>
          <div className="card-b">
            <div className="wotl" style={{ marginBottom: 14 }}>
              <div className="step done"><div className="node"><svg width="13" height="13"><use href="#i-chk" /></svg></div><div className="lbl">Done</div></div>
              <div className="step now"><div className="node"><svg width="13" height="13"><use href="#i-wrench" /></svg></div><div className="lbl">Active</div></div>
              <div className="step"><div className="node"><svg width="13" height="13"><use href="#i-clock" /></svg></div><div className="lbl">Pending</div></div>
            </div>
            <div className="vtl">
              <div className="ev ok"><b className="t-md">Event resolved</b><div className="t-sm muted">Vertical timeline variant</div></div>
              <div className="ev live"><b className="t-md">Event in progress</b><div className="t-sm muted">With live indicator</div></div>
            </div>
          </div>
        </div>

        {/* Table */}
        <div className="card">
          <div className="card-h"><h3>Data Table</h3></div>
          <table className="tbl">
            <thead><tr><th>Header 1</th><th>Header 2</th><th>Header 3</th></tr></thead>
            <tbody>
              <tr><td className="strong">Row data</td><td className="mono">1,250</td><td><span className="badge b-normal">Normal</span></td></tr>
              <tr><td className="strong">Row data</td><td className="mono">8.2</td><td><span className="badge b-crit">Critical</span></td></tr>
            </tbody>
          </table>
        </div>

        {/* Progress + Callouts */}
        <div className="card" style={{ gridColumn: 'span 2' }}>
          <div className="card-h"><h3>Callouts &amp; Progress</h3></div>
          <div className="card-b">
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))' }}>
              <div className="callout co-good"><svg width="16" height="16" style={{ color: 'var(--good)', flex: 'none' }}><use href="#i-chk" /></svg><span className="t-sm">Success / verified state</span></div>
              <div className="callout co-warn"><svg width="16" height="16" style={{ color: 'var(--warn)', flex: 'none' }}><use href="#i-alert" /></svg><span className="t-sm">Warning / attention needed</span></div>
              <div className="callout co-crit"><svg width="16" height="16" style={{ color: 'var(--crit)', flex: 'none' }}><use href="#i-x" /></svg><span className="t-sm">Critical / failure state</span></div>
              <div className="callout co-info"><svg width="16" height="16" style={{ color: '#0A7EA3', flex: 'none' }}><use href="#i-drop" /></svg><span className="t-sm">Informational / in progress</span></div>
            </div>
            <div style={{ marginTop: 14 }}>
              <div className="prog"><i style={{ width: '64%' }} /></div>
              <div className="prog crit" style={{ marginTop: 8 }}><i style={{ width: '32%' }} /></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
