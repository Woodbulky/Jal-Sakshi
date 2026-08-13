'use client';
import { usePathname, useRouter } from 'next/navigation';

const NAV_ITEMS = [
  { group: 'Operations', items: [
    { label: 'Dashboard', icon: '#i-chart', href: '/dashboard', pip: null },
    { label: 'Incidents', icon: '#i-alert', href: '/dashboard/incidents', pip: '4' },
    { label: 'Work Orders', icon: '#i-wrench', href: '/dashboard/workorders', pip: '7' },
    { label: 'Verification', icon: '#i-shield', href: '/dashboard/verification', pip: null },
  ]},
  { group: 'Network', items: [
    { label: 'Assets', icon: '#i-asset', href: '/dashboard/assets', pip: null },
    { label: 'Telemetry', icon: '#i-chart', href: '/dashboard/telemetry', pip: null },
  ]},
  { group: 'Agent', items: [
    { label: 'Agent & Comms', icon: '#i-agent', href: '/dashboard/agents', pip: null },
    { label: 'Escalation', icon: '#i-send', href: '/dashboard/escalation', pip: '3' },
  ]},
  { group: 'System', items: [
    { label: 'Demo Control', icon: '#i-bolt', href: '/dashboard/demo', pip: null },
    { label: 'Design System', icon: '#i-settings', href: '/dashboard/design', pip: null },
  ]},
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  function isActive(href: string) {
    if (href === '/dashboard') return pathname === '/dashboard';
    return pathname.startsWith(href);
  }

  return (
    <div className="sidebar">
      {NAV_ITEMS.map((group) => (
        <div key={group.group}>
          <div className="nav-grp">{group.group}</div>
          {group.items.map((item) => (
            <button
              key={item.href}
              className={`nav ${isActive(item.href) ? 'on' : ''}`}
              onClick={() => router.push(item.href)}
            >
              <svg width="16" height="16"><use href={item.icon} /></svg>
              <span className="nt">{item.label}</span>
              {item.pip && <span className="pip">{item.pip}</span>}
            </button>
          ))}
        </div>
      ))}

      {/* Agent runtime footer */}
      <div className="sb-foot">
        <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase' as const, color: '#5B84A8', marginBottom: 7 }}>
          Agent Runtime
        </div>
        <div className="row gap6" style={{ marginBottom: 5 }}>
          <span className="pulse-dot" style={{ color: '#22B463' }} />
          <span style={{ fontSize: 11.5, color: '#8FE3B4', fontWeight: 600 }}>Active</span>
        </div>
        <div style={{ fontSize: 10.5, color: '#5B84A8', lineHeight: 1.45 }}>
          LangGraph · 4 nodes<br />
          Last decision: 12s ago
        </div>
      </div>
    </div>
  );
}
