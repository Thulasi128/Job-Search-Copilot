import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { 
  PlusCircle, Search, Link as LinkIcon, FileText, 
  RefreshCw, CheckCircle2, AlertCircle, Clock, ChevronRight 
} from 'lucide-react';

export default function JobsBoardPage({ onSelectJob }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [intakeMode, setIntakeMode] = useState('text'); // 'text' | 'url'
  const [jdText, setJdText] = useState('');
  const [url, setUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [alert, setAlert] = useState(null);

  useEffect(() => {
    loadJobs();
  }, []);

  // Auto-polling for active background executions
  useEffect(() => {
    const hasActive = jobs.some(
      (j) => j.status === 'processing' || j.status === 'drafting'
    );
    if (!hasActive) return;

    const interval = setInterval(() => {
      loadJobs(false);
    }, 3000);
    return () => clearInterval(interval);
  }, [jobs]);

  async function loadJobs(showLoading = true) {
    if (showLoading) setLoading(true);
    try {
      const data = await api.getJobs();
      setJobs(data);
    } catch (err) {
      console.error(err);
    } finally {
      if (showLoading) setLoading(false);
    }
  }

  async function handleAddJob(e) {
    e.preventDefault();
    setAlert(null);

    const payload = {};
    if (intakeMode === 'text') {
      if (jdText.trim().length < 200) {
        setAlert({ type: 'error', message: 'Job description text must be at least 200 characters.' });
        return;
      }
      payload.jd_text = jdText.trim();
    } else {
      if (!url.trim() || (!url.startsWith('http://') && !url.startsWith('https://'))) {
        setAlert({ type: 'error', message: 'Please enter a valid http:// or https:// URL.' });
        return;
      }
      payload.url = url.trim();
    }

    setSubmitting(true);
    try {
      const res = await api.createJob(payload);
      setAlert({
        type: 'success',
        message: 'Job submitted! Workflow started in background. Analyzing fit & tailoring...',
      });
      setJdText('');
      setUrl('');
      await loadJobs(false);
      if (res.job_id) {
        onSelectJob(res.job_id);
      }
    } catch (err) {
      setAlert({ type: 'error', message: err.message || 'Failed to submit job.' });
    } finally {
      setSubmitting(false);
    }
  }

  const filteredJobs = jobs.filter((j) => {
    const matchesSearch =
      (j.company || '').toLowerCase().includes(search.toLowerCase()) ||
      (j.title || '').toLowerCase().includes(search.toLowerCase());

    if (!matchesSearch) return false;
    if (statusFilter === 'all') return true;
    if (statusFilter === 'active') {
      return ['processing', 'drafting', 'awaiting_confirmation', 'awaiting_approval', 'awaiting_manual_edit'].includes(j.status);
    }
    if (statusFilter === 'approved') {
      return ['approved', 'applied', 'interview'].includes(j.status);
    }
    if (statusFilter === 'failed') return j.status === 'failed';
    if (statusFilter === 'closed') return ['skipped', 'rejected', 'closed'].includes(j.status);
    return true;
  });

  function getStatusBadge(status) {
    const styles = {
      processing: 'bg-blue-50 text-blue-700 border-blue-200 animate-pulse',
      drafting: 'bg-indigo-50 text-indigo-700 border-indigo-200 animate-pulse',
      awaiting_confirmation: 'bg-amber-50 text-amber-700 border-amber-200 font-semibold',
      awaiting_approval: 'bg-emerald-50 text-emerald-700 border-emerald-300 font-semibold',
      awaiting_manual_edit: 'bg-orange-50 text-orange-700 border-orange-300 font-semibold',
      approved: 'bg-emerald-600 text-white font-medium',
      applied: 'bg-teal-700 text-white font-medium',
      interview: 'bg-purple-700 text-white font-medium',
      rejected: 'bg-slate-200 text-slate-700',
      skipped: 'bg-slate-100 text-slate-500',
      closed: 'bg-slate-200 text-slate-600',
      failed: 'bg-rose-50 text-rose-700 border-rose-300 font-semibold',
      saved: 'bg-slate-100 text-slate-700',
    };

    const label = status ? status.replace(/_/g, ' ') : 'unknown';
    return (
      <span className={`px-2.5 py-1 text-xs rounded-full border capitalize inline-flex items-center gap-1 ${styles[status] || styles.saved}`}>
        {label}
      </span>
    );
  }

  function getScoreBadge(score) {
    if (score === null || score === undefined) {
      return <span className="text-slate-400 text-xs">—</span>;
    }
    let color = 'bg-slate-100 text-slate-700 border-slate-200';
    if (score >= 70) color = 'bg-emerald-50 text-emerald-700 border-emerald-200 font-bold';
    else if (score >= 40) color = 'bg-amber-50 text-amber-700 border-amber-200 font-semibold';
    else color = 'bg-rose-50 text-rose-700 border-rose-200 font-semibold';

    return (
      <span className={`px-2 py-0.5 text-xs rounded-md border ${color}`}>
        {score}%
      </span>
    );
  }

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Internship Application Board</h1>
        <p className="text-slate-500 mt-1">
          Add new internship job postings to evaluate match fit, tailor bullets, and prepare human-approved applications.
        </p>
      </div>

      {alert && (
        <div
          className={`p-4 rounded-lg flex items-start gap-3 ${
            alert.type === 'success' ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' : 'bg-rose-50 text-rose-800 border border-rose-200'
          }`}
        >
          {alert.type === 'success' ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-600 mt-0.5 shrink-0" />
          ) : (
            <AlertCircle className="w-5 h-5 text-rose-600 mt-0.5 shrink-0" />
          )}
          <span className="text-sm font-medium">{alert.message}</span>
        </div>
      )}

      {/* Ingest Job Card */}
      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
            <PlusCircle className="w-5 h-5 text-emerald-600" />
            Add Internship Opportunity
          </h2>
          <div className="flex bg-slate-100 p-1 rounded-lg text-xs font-medium">
            <button
              type="button"
              onClick={() => setIntakeMode('text')}
              className={`px-3 py-1 rounded-md transition ${intakeMode === 'text' ? 'bg-white text-slate-900 shadow-2xs' : 'text-slate-600'}`}
            >
              Paste JD Text
            </button>
            <button
              type="button"
              onClick={() => setIntakeMode('url')}
              className={`px-3 py-1 rounded-md transition ${intakeMode === 'url' ? 'bg-white text-slate-900 shadow-2xs' : 'text-slate-600'}`}
            >
              Public URL
            </button>
          </div>
        </div>

        <form onSubmit={handleAddJob} className="space-y-4">
          {intakeMode === 'text' ? (
            <div>
              <div className="flex justify-between items-center text-xs text-slate-500 mb-1">
                <span>Job Description text</span>
                <span className={jdText.length < 200 ? 'text-amber-600 font-medium' : 'text-emerald-600'}>
                  {jdText.length} / 200 min characters
                </span>
              </div>
              <textarea
                rows={5}
                value={jdText}
                onChange={(e) => setJdText(e.target.value)}
                placeholder="Paste the full job posting description here (roles, required skills, responsibilities)..."
                className="w-full p-3 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
          ) : (
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Job Posting Public URL</label>
              <div className="flex gap-2">
                <input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://company.com/careers/internship-role"
                  className="flex-1 px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                SSRF-guarded. Private networks and login-gated sites are blocked.
              </p>
            </div>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold rounded-lg flex items-center gap-2 transition disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${submitting ? 'animate-spin' : ''}`} />
              {submitting ? 'Analyzing & Starting Workflow...' : 'Ingest & Tailor'}
            </button>
          </div>
        </form>
      </div>

      {/* Filter and Jobs List */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        {/* Toolbar */}
        <div className="p-4 border-b border-slate-200 flex flex-col md:flex-row gap-4 justify-between items-center">
          <div className="relative w-full md:w-72">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search company or title..."
              className="w-full pl-9 pr-3 py-1.5 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div className="flex gap-1.5 overflow-x-auto w-full md:w-auto">
            {['all', 'active', 'approved', 'failed', 'closed'].map((filterKey) => (
              <button
                key={filterKey}
                onClick={() => setStatusFilter(filterKey)}
                className={`px-3 py-1 text-xs rounded-lg font-medium capitalize transition ${
                  statusFilter === filterKey ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {filterKey}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        {loading ? (
          <div className="text-center py-12 text-slate-400 text-sm">Loading jobs board...</div>
        ) : filteredJobs.length === 0 ? (
          <div className="text-center py-12 text-slate-400 text-sm">
            No matching jobs found. Ingest an internship opportunity above to get started.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-600 uppercase text-[10px] tracking-wider border-b border-slate-200">
                <tr>
                  <th className="py-3 px-4">Opportunity</th>
                  <th className="py-3 px-4">Source</th>
                  <th className="py-3 px-4 text-center">Fit Score</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Date</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {filteredJobs.map((job) => (
                  <tr
                    key={job.id}
                    onClick={() => onSelectJob(job.id)}
                    className="hover:bg-slate-50/80 cursor-pointer transition"
                  >
                    <td className="py-3.5 px-4">
                      <div className="font-semibold text-slate-900 text-sm">{job.title || 'Unknown Title'}</div>
                      <div className="text-slate-500">{job.company || 'Unknown Company'}</div>
                    </td>
                    <td className="py-3.5 px-4 font-mono text-[11px] text-slate-500">
                      {job.source?.startsWith('http') ? (
                        <span className="flex items-center gap-1 text-emerald-600">
                          <LinkIcon className="w-3 h-3" /> URL
                        </span>
                      ) : (
                        <span className="flex items-center gap-1">
                          <FileText className="w-3 h-3 text-slate-400" /> Pasted
                        </span>
                      )}
                    </td>
                    <td className="py-3.5 px-4 text-center">{getScoreBadge(job.score)}</td>
                    <td className="py-3.5 px-4">{getStatusBadge(job.status)}</td>
                    <td className="py-3.5 px-4 text-slate-400">
                      {job.created_at ? new Date(job.created_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectJob(job.id);
                        }}
                        className="p-1.5 hover:bg-slate-200 text-slate-600 rounded-md transition inline-flex items-center"
                      >
                        <ChevronRight className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

