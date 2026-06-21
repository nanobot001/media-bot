import { useState } from 'react';
import { Activity, Tv, Compass, Search } from 'lucide-react';
import { useSSE } from './hooks/useSSE';

type Tab = 'dashboard' | 'audit' | 'library' | 'discovery';

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const { status, connected } = useSSE('http://localhost:8000/api/stream');

  const primaryTabs = [
    { id: 'dashboard', label: 'Dashboard', icon: Activity },
    { id: 'audit', label: 'Audit', icon: Search },
    { id: 'library', label: 'Library', icon: Tv },
    { id: 'discovery', label: 'Discovery', icon: Compass },
  ] as const;

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <header className="glass app-header">
        <div className="container flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="app-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              Media Bot UI
              <span className="badge badge-default" style={{ fontSize: '0.65rem', opacity: 0.7 }}>v1.5.3</span>
            </h1>
            <span className={`badge ${connected ? 'badge-success' : 'badge-danger'}`}>
              <span className="hide-mobile">{connected ? 'Backend Online' : 'Backend Offline'}</span>
            </span>
            {status.state === 'running' && (
              <span className="badge badge-info animate-pulse">Job Running</span>
            )}
          </div>
          <nav className="nav-links">
            {primaryTabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as Tab)}
                className={`nav-button ${activeTab === tab.id ? 'active' : ''}`}
                title={tab.label}
              >
                <tab.icon size={20} />
                <span className="hide-mobile">{tab.label}</span>
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="container flex-1" style={{ padding: '2rem 0' }}>
        {activeTab === 'dashboard' && (
          <div className="glass-panel">
            <h2>System Dashboard</h2>
            <p>Welcome to Media Bot UI. Select a tab above to manage your library.</p>
            <div className="grid grid-cols-3 gap-4" style={{ marginTop: '2rem' }}>
              <div className="glass-panel">
                <h3>Backend Status</h3>
                <p style={{ color: connected ? 'var(--success)' : 'var(--danger)' }}>
                  {connected ? 'Connected via SSE' : 'Disconnected'}
                </p>
              </div>
              <div className="glass-panel">
                <h3>System Uptime</h3>
                <p>{connected ? `${status.uptime} seconds` : 'N/A'}</p>
              </div>
              <div className="glass-panel">
                <h3>Engine State</h3>
                <p>{status.state.toUpperCase()}</p>
              </div>
            </div>
          </div>
        )}
        
        {activeTab !== 'dashboard' && (
          <div className="glass-panel">
            <h2>{primaryTabs.find(t => t.id === activeTab)?.label}</h2>
            <p>This module will interface with the FastAPI endpoints in the next step.</p>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
