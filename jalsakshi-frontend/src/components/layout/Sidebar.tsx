'use client';
import { usePathname, useRouter } from 'next/navigation';
import { useApiResource } from '@/hooks/useApiResource';
import { useNow } from '@/hooks/useNow';
import { getDashboardSummary, listDecisions } from '@/lib/api/endpoints';

/**
 * `pip` names which live count sits on a nav item, rather than carrying a
 * number. The counts were once literals — a console that showed four incidents
 * on an empty network — and a demo is judged on whether its numbers are real.
 */
type Pip = 'incidents' | 'workOrders' | 'escalations' | null;

const NAV_ITEMS: Array<{
  group: string;
  items: Array<{ label: string; icon: string; href: string; pip: Pip }>;
}> = [
  { group: 'Operations', items: [
    { label: 'Dashboard', icon: '#i-chart', href: '/dashboard', pip: null },
    { label: 'Incidents', icon: '#i-alert', href: '/dashboard/incidents', pip: 'incidents' },
    { label: 'Work Orders', icon: '#i-wrench', href: '/dashboard/workorders', pip: 'workOrders' },
    { label: 'Verification', icon: '#i-shield', href: '/dashboard/verification', pip: null },
  ]},
  { group: 'Network', items: [
    { label: 'Assets', icon: '#i-asset', href: '/dashboard/assets', pip: null },
    { label: 'Telemetry', icon: '#i-chart', href: '/dashboard/telemetry', pip: null },
  ]},
  { group: 'Agent', items: [
    { label: 'Agent & Comms', icon: '#i-agent', href: '/dashboard/agents', pip: null },
    { label: 'Escalation', icon: '#i-send', href: '/dashboard/escalation', pip: 'escalations' },
  ]},
  { group: 'System', items: [
    { label: 'Demo Control', icon: '#i-bolt', href: '/dashboard/demo', pip: null },
    { label: 'Design System', icon: '#i-settings', href: '/dashboard/design', pip: null },
  ]},
];

/** "12s ago", "4m ago". Undefined when the agent has never run. */
function ago(iso: string | null | undefined, now: number): string | null {
  if (!iso) return null;
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const now = useNow(5000);

  const summary = useApiResource((signal) => getDashboardSummary(72, { signal }), {
    intervalMs: 10000,
  });
  const decisions = useApiResource((signal) => listDecisions({ limit: 1, signal }), {
    intervalMs: 10000,
  });

  // A breached SLA is what escalation exists for, so it is the count that
  // belongs on that item — not the number of escalation rows ever written.
  const counts: Record<Exclude<Pip, null>, number> = {
    incidents: summary.data?.open_incidents ?? 0,
    workOrders: summary.data?.open_work_orders ?? 0,
    escalations: summary.data?.sla_breached ?? 0,
  };

  const lastDecision = ago(decisions.data?.[0]?.ts, now);

  function isActive(href: string) {
    if (href === '/dashboard') return pathname === '/dashboard';
    return pathname.startsWith(href);
  }

  return (
    <div className="sidebar">
      {NAV_ITEMS.map((group) => (
        <div key={group.group}>
          <div className="nav-grp">{group.group}</div>
          {group.items.map((item) => {
            // Zero is not news: an empty network shows no pip at all rather
            // than a nought that reads like an unread badge.
            const count = item.pip ? counts[item.pip] : 0;
            return (
              <button
                key={item.href}
                className={`nav ${isActive(item.href) ? 'on' : ''}`}
                onClick={() => router.push(item.href)}
              >
                <svg width="16" height="16"><use href={item.icon} /></svg>
                <span className="nt">{item.label}</span>
                {count > 0 && <span className="pip">{count}</span>}
              </button>
            );
          })}
        </div>
      ))}

      {/* Agent runtime footer */}
      <div className="sb-foot">
        <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase' as const, color: '#5B84A8', marginBottom: 7 }}>
          Agent Runtime
        </div>
        <div className="row gap6" style={{ marginBottom: 5 }}>
          <span
            className="pulse-dot"
            style={{ color: summary.offline ? '#EF4444' : '#22B463' }}
          />
          <span
            style={{
              fontSize: 11.5,
              color: summary.offline ? '#F1A3A3' : '#8FE3B4',
              fontWeight: 600,
            }}
          >
            {summary.offline ? 'Unreachable' : 'Active'}
          </span>
        </div>
        <div style={{ fontSize: 10.5, color: '#5B84A8', lineHeight: 1.45 }}>
          LangGraph · 4 nodes<br />
          {lastDecision ? `Last decision: ${lastDecision}` : 'No decisions yet'}
        </div>
      </div>
    </div>
  );
}
