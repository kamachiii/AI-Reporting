import { useState } from 'react';
import { Users, Database, Bot, FileText, LogOut, Building2 } from 'lucide-react';
import toast from 'react-hot-toast';

import CompanyBranchesTab from './CompanyBranchesTab';
import TenantsTab from './TenantsTab';
import AIConfigTab from './AIConfigTab';
import UsersTab from './UsersTab';
import AuditLogTab from './AuditLogTab';

export default function AdminLayout({ user, onLogout }) {
  const [activeTab, setActiveTab] = useState('company');

  const tabs = [
    { id: 'company', label: 'Perusahaan & Cabang', icon: Building2 },
    { id: 'tenants', label: 'Database & Tenant', icon: Database },
    { id: 'ai', label: 'Penyedia & Model AI', icon: Bot },
    { id: 'users', label: 'Pengguna & Izin', icon: Users },
    { id: 'audit', label: 'Audit Log & Monitoring', icon: FileText },
  ];

  const renderTabContent = () => {
    switch (activeTab) {
      case 'company': return <CompanyBranchesTab />;
      case 'tenants': return <TenantsTab />;
      case 'ai': return <AIConfigTab />;
      case 'users': return <UsersTab />;
      case 'audit': return <AuditLogTab />;
      default: return <div>Tab tidak dikenal</div>;
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex">
      <aside className="w-64 bg-white border-r border-hairline flex flex-col h-screen fixed top-0 left-0 z-10">
        <div className="p-6 border-b border-hairline">
          <h1 className="font-serif text-lg text-ink">DMS AI Platform</h1>
          <p className="text-xs text-muted">Panel Admin Sistem</p>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-md text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted hover:bg-surface-soft hover:text-ink'
                }`}
              >
                <Icon size={18} />
                {tab.label}
              </button>
            );
          })}
        </nav>
        <div className="p-4 border-t border-hairline">
          <button
            onClick={() => {
              onLogout();
              toast('Logout berhasil');
            }}
            className="flex items-center gap-3 text-sm text-muted hover:text-ink transition-colors"
          >
            <LogOut size={18} />
            Keluar
          </button>
        </div>
      </aside>

      <main className="ml-64 flex-1 p-8 min-h-screen">
        <div className="max-w-6xl mx-auto space-y-6">
          <header className="flex items-center justify-between">
            <div>
              <h2 className="font-serif text-2xl text-ink">Dashboard Admin</h2>
              <p className="text-muted text-sm">Pengelolaan Multi-Tenant, AI, Pengguna, & Log</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="px-3 py-1 bg-primary/10 text-primary text-xs font-medium rounded-full">
                Administrator{user?.username ? ` · ${user.username}` : ''}
              </span>
            </div>
          </header>

          <div className="bg-white rounded-xl border border-hairline shadow-sm p-6">
            {renderTabContent()}
          </div>
        </div>
      </main>
    </div>
  );
}