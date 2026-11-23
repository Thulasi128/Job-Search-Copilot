import React, { useState, useEffect } from 'react';
import { api } from './api';
import ProfilePage from './pages/ProfilePage';
import JobsBoardPage from './pages/JobsBoardPage';
import JobDetailPage from './pages/JobDetailPage';
import LogsPage from './pages/LogsPage';
import { 
  Briefcase, User, ScrollText, CheckCircle2, 
  XCircle, Sparkles, Shield
} from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('profile');
  const [selectedJobId, setSelectedJobId] = useState(null);
  const [health, setHealth] = useState({ status: 'checking', database: 'unknown' });

  useEffect(() => {
    checkHealth();
  }, []);

  async function checkHealth() {
    try {
      const res = await api.getHealth();
      setHealth(res);
    } catch {
      setHealth({ status: 'error', database: 'disconnected' });
    }
  }

  function handleSelectJob(jobId) {
    setSelectedJobId(jobId);
    setActiveTab('job-detail');
  }

  function handleBackToBoard() {
    setSelectedJobId(null);
    setActiveTab('jobs');
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col text-slate-800">
      {/* Top Navigation Bar */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-50 shadow-2xs">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-3 cursor-pointer" onClick={() => setActiveTab('jobs')}>
            <div className="w-9 h-9 bg-emerald-600 rounded-xl flex items-center justify-center text-white shadow-sm shadow-emerald-500/20">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <span className="font-bold text-base text-slate-900 tracking-tight block">Job-Search Copilot</span>
              <span className="text-[10px] text-slate-400 font-medium tracking-wide uppercase flex items-center gap-1">
                <Shield className="w-3 h-3 text-emerald-600" /> Student Internship Assistant
              </span>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="flex items-center gap-1">
            <button
              onClick={() => {
                setSelectedJobId(null);
                setActiveTab('profile');
              }}
              className={`px-3.5 py-2 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition ${
                activeTab === 'profile'
                  ? 'bg-emerald-50 text-emerald-800 border border-emerald-200 shadow-2xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
            >
              <User className="w-4 h-4" /> Profile & Prefs
            </button>

            <button
              onClick={() => {
                setSelectedJobId(null);
                setActiveTab('jobs');
              }}
              className={`px-3.5 py-2 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition ${
                activeTab === 'jobs' || activeTab === 'job-detail'
                  ? 'bg-emerald-50 text-emerald-800 border border-emerald-200 shadow-2xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
            >
              <Briefcase className="w-4 h-4" /> Jobs Board
            </button>

            <button
              onClick={() => {
                setSelectedJobId(null);
                setActiveTab('logs');
              }}
              className={`px-3.5 py-2 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition ${
                activeTab === 'logs'
                  ? 'bg-emerald-50 text-emerald-800 border border-emerald-200 shadow-2xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
            >
              <ScrollText className="w-4 h-4" /> Audit Logs
            </button>
          </nav>

          {/* System Health Status Indicator */}
          <div className="hidden sm:flex items-center gap-2 pl-4 border-l border-slate-200 text-xs">
            {health.status === 'ok' ? (
              <span className="flex items-center gap-1.5 text-emerald-700 font-medium">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                API Connected
              </span>
            ) : health.status === 'checking' ? (
              <span className="text-slate-400">Connecting...</span>
            ) : (
              <span className="flex items-center gap-1.5 text-rose-600 font-medium">
                <XCircle className="w-3.5 h-3.5" /> Offline
              </span>
            )}
          </div>
        </div>
      </header>

      {/* Main Content View */}
      <main className="flex-1 max-w-6xl w-full mx-auto px-4 py-8">
        {activeTab === 'profile' && <ProfilePage />}
        {activeTab === 'jobs' && <JobsBoardPage onSelectJob={handleSelectJob} />}
        {activeTab === 'job-detail' && <JobDetailPage jobId={selectedJobId} onBack={handleBackToBoard} />}
        {activeTab === 'logs' && <LogsPage />}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-200 bg-white py-4 text-center text-xs text-slate-400">
        <p>Local Privacy-First Multi-Agent Architecture • Never Fabricates Content • Nothing Auto-Sent</p>
      </footer>
    </div>
  );
}

