'use client';
import { useEffect, useState } from 'react';
import { useBackendStatus } from '@/hooks/useBackendStatus';
import { useIncidents } from '@/hooks/useIncidents';

/** The field crew's Telegram group — where every dispatch actually lands.
 *  A public invite link, so it belongs in the client bundle rather than an
 *  env var: anyone looking at the console is meant to be able to join and
 *  watch the loop close. */
const FIELD_GROUP_URL = 'https://t.me/+TOa4JHNTkygwNjc1';

export default function Topbar() {
  const [clock, setClock] = useState('');
  const backend = useBackendStatus();
  const { summary } = useIncidents({ intervalMs: 15_000 });

  useEffect(() => {
    function updateClock() {
      const d = new Date();
      const pad = (n: number) => String(n).padStart(2, '0');
      setClock(`${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())} IST`);
    }
    updateClock();
    const iv = setInterval(updateClock, 1000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="topbar">
      <div className="tb-brand">
        <div style={{
          width: 24, height: 24, borderRadius: '50%',
          background: 'linear-gradient(140deg, #1583CE, #0E9FCB)',
          display: 'grid', placeItems: 'center',
        }}>
          <svg width="13" height="13" style={{ color: '#fff' }}>
            <use href="#i-drop" />
          </svg>
        </div>
        JAL-SAKSHI
      </div>

      <div className="areapick">
        <svg width="13" height="13" style={{ color: '#A8C2DA' }}>
          <use href="#i-drop" />
        </svg>
        <span>{summary?.service_area_name ?? 'Vitpur'}, Ichhawar</span>
        <svg width="10" height="10" style={{ color: '#6E8EAC', marginLeft: 2 }}>
          <use href="#i-back" style={{ transform: 'rotate(-90deg)' } as React.CSSProperties} />
        </svg>
      </div>

      <div className="sysok" title={backend.health ? `classifier: ${backend.health.classifier}` : undefined}>
        <span className="pulse-dot" />
        {backend.state === 'live' ? 'System Healthy' : backend.label}
      </div>

      <div className="spacer" />

      <span className="mono hide-sm" style={{
        fontSize: 11.5, color: '#7FA6C2', letterSpacing: '.03em',
      }}>
        {clock}
      </span>

      <a
        className="tb-ico"
        href={FIELD_GROUP_URL}
        target="_blank"
        rel="noreferrer"
        title="Open the field crew's Telegram group"
        aria-label="Open the field crew's Telegram group"
      >
        <svg width="16" height="16"><use href="#i-tg" /></svg>
        {summary?.open_work_orders ? <span className="cnt">{summary.open_work_orders}</span> : null}
      </a>
      <button className="tb-ico" title="Open incidents">
        <svg width="16" height="16"><use href="#i-bell" /></svg>
        {summary?.open_incidents ? <span className="cnt">{summary.open_incidents}</span> : null}
      </button>

      <div className="tb-user">
        <div className="av">SK</div>
        <span className="hide-sm" style={{ fontSize: 12, fontWeight: 600, color: '#D6E7F2' }}>
          Operator
        </span>
      </div>
    </div>
  );
}
