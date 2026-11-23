import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { 
  ScrollText, RefreshCw, CheckCircle2, AlertCircle, 
  Clock, Filter, ShieldCheck 
} from 'lucide-react';

export default function LogsPage() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [jobIdFilter, setJobIdFilter] = useState('');

  useEffect(() => {
    loadLogs();
  }, []);

  async function loadLogs(filter = jobIdFilter) {
    setLoading(true);
    try {
      const data = await api.getLogs(filter || null, 100);
      setLogs(data);
    } catch (err) {
      console.error('Failed to load logs:', err);
    } finally {
      setLoading(false);
    }
  }

  function handleFilterSubmit(e) {
    e.preventDefault();
    loadLogs(jobIdFilter.trim());
  }

  function getAgentBadge(name) {
    const colors = {
      profile_agent: 'bg-blue-50 text-blue-700 border-blue-200',
      intake_agent: 'bg-cyan-50 text-cyan-700 border-cyan-200',
      matching_agent: 'bg-purple-50 text-purple-700 border-purple-200',
      tailor_agent: 'bg-indigo-50 text-indigo-700 border-indigo-200',
      cover_note_agent: 'bg-teal-50 text-teal-700 border-teal-200',
      verifier_agent: 'bg-amber-50 text-amber-700 border-amber-200',
      draft_pipeline: 'bg-emerald-50 text-emerald-700 border-emerald-200',
      workflow_runner: 'bg-slate-100 text-slate-800 border-slate-300',
      workflow_router: 'bg-slate-100 text-slate-700 border-slate-200',
    };

    return (
      <span className={`px-2 py-0.5 text-xs font-mono rounded-md border ${colors[name] || 'bg-slate-100 text-slate-700 border-slate-200'}`}>
        {name}
      </span>
    );
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <ScrollText className="w-6 h-6 text-emerald-600" />
            Agent Audit Log Timeline
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Complete privacy-compliant audit trail of every agent action and workflow event.
          </p>
        </div>

        <button
          type="button"
          onClick={() => loadLogs()}
          disabled={loading}
          className="px-3.5 py-1.5 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition shadow-2xs self-start md:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Filter Toolbar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-3">
        <form onSubmit={handleFilterSubmit} className="flex gap-2 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-72">
            <Filter className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              value={jobIdFilter}
              onChange={(e) => setJobIdFilter(e.target.value)}
              placeholder="Filter by Job ID..."
              className="w-full pl-9 pr-3 py-1.5 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono"
            />
          </div>
          <button
            type="submit"
            className="px-3 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-semibold hover:bg-slate-800 transition"
          >
            Filter
          </button>
          {jobIdFilter && (
            <button
              type="button"
              onClick={() => {
                setJobIdFilter('');
                loadLogs('');
              }}
              className="px-2.5 py-1.5 bg-slate-100 text-slate-600 rounded-lg text-xs font-medium hover:bg-slate-200 transition"
            >
              Clear
            </button>
          )}
        </form>

        <div className="flex items-center gap-1.5 text-xs text-slate-500 font-medium">
          <ShieldCheck className="w-4 h-4 text-emerald-600" />
          <span>Zero raw document content logged (Hard Rule 7)</span>
        </div>
      </div>

      {/* Timeline List */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
        {loading ? (
          <div className="text-center py-16 text-slate-400 text-sm">
            <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-emerald-600" />
            Loading audit events...
          </div>
        ) : logs.length === 0 ? (
          <div className="text-center py-16 text-slate-400 text-sm">
            No audit log entries found.
          </div>
        ) : (
          <div className="space-y-6 relative before:absolute before:inset-0 before:left-3.5 before:w-0.5 before:bg-slate-200">
            {logs.map((log, idx) => (
              <div key={idx} className="relative flex items-start gap-4 pl-8">
                {/* Timeline Node Icon */}
                <div
                  className={`absolute left-1.5 top-1 w-5 h-5 rounded-full border-2 bg-white flex items-center justify-center -translate-x-1/2 ${
                    log.status === 'success' ? 'border-emerald-500' : 'border-rose-500'
                  }`}
                >
                  <div
                    className={`w-2 h-2 rounded-full ${
                      log.status === 'success' ? 'bg-emerald-500' : 'bg-rose-500'
                    }`}
                  />
                </div>

                {/* Entry Card */}
                <div className="flex-1 bg-slate-50 border border-slate-200 rounded-lg p-3.5 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2">
                    <div className="flex items-center gap-2">
                      {getAgentBadge(log.agent_name)}
                      <span
                        className={`px-2 py-0.5 text-[10px] uppercase font-bold rounded ${
                          log.status === 'success'
                            ? 'bg-emerald-100 text-emerald-800'
                            : 'bg-rose-100 text-rose-800'
                        }`}
                      >
                        {log.status}
                      </span>
                    </div>

                    <div className="flex items-center gap-1 text-[11px] text-slate-400 font-mono">
                      <Clock className="w-3.5 h-3.5" />
                      {log.timestamp ? new Date(log.timestamp).toLocaleString() : '—'}
                    </div>
                  </div>

                  {/* Job ID reference if present */}
                  {log.job_id && (
                    <div className="text-[11px] font-mono text-slate-500">
                      Linked Job ID:{' '}
                      <span className="font-semibold text-slate-700 bg-slate-200/70 px-1 py-0.5 rounded">
                        {log.job_id}
                      </span>
                    </div>
                  )}

                  {/* Summary Details */}
                  {log.summary && Object.keys(log.summary).length > 0 && (
                    <div className="bg-white p-2.5 rounded border border-slate-200 text-xs text-slate-700 space-y-1">
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
                        {Object.entries(log.summary).map(([key, val]) => (
                          <div key={key}>
                            <span className="text-slate-400 block capitalize">{key.replace(/_/g, ' ')}:</span>
                            <span className="font-semibold text-slate-800">
                              {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

