import Topbar from '@/components/layout/Topbar';
import Sidebar from '@/components/layout/Sidebar';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <Topbar />
      <div className="shell">
        <Sidebar />
        <main className="main">
          {children}
        </main>
      </div>
    </div>
  );
}
