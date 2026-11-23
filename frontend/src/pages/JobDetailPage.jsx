import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { 
  ArrowLeft, CheckCircle2, AlertTriangle, AlertCircle, 
  Download, RefreshCw, Send, XCircle, Edit3, ShieldAlert, Check
} from 'lucide-react';

export default function JobDetailPage({ jobId, onBack }) {
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [alert, setAlert] = useState(null);

  // Editable draft state
  const [editedSkills, setEditedSkills] = useState('');
  const [editedCoverNote, setEditedCoverNote] = useState('');
  const [acknowledgeWarnings, setAcknowledgeWarnings] = useState(false);
  const [isEditingDraft, setIsEditingDraft] = useState(false);

  useEffect(() => {
    loadJob();
  }, [jobId]);

  // Polling for processing/drafting statuses
  useEffect(() => {
    if (!job || !['processing', 'drafting'].includes(job.status)) return;
    const interval = setInterval(() => {
      loadJob(false);
    }, 2500);
    return () => clearInterval(interval);
  }, [job]);

  async function loadJob(showLoading = true) {
    if (showLoading) setLoading(true);
    try {
      const data = await api.getJobDetail(jobId);
      setJob(data);

      if (data.draft) {
        setEditedSkills(data.draft.tailored_resume?.skills_section?.join(', ') || '');
        setEditedCoverNote(data.draft.cover_note?.text || '');
      }
    } catch (err) {
      setAlert({ type: 'error', message: err.message || 'Failed to load job details.' });
    } finally {
      if (showLoading) setLoading(false);
    }
  }

  async function handleDecision(action, includeEdits = false) {
    setActionLoading(true);
    setAlert(null);
    try {
      const payload = { action, acknowledge_warnings: acknowledgeWarnings };

      if (includeEdits) {
        payload.edits = {
          skills_section: editedSkills.split(',').map((s) => s.trim()).filter(Boolean),
          cover_note: editedCoverNote.trim(),
        };
      }

      await api.submitDecision(jobId, payload);
      setAlert({ type: 'success', message: `Decision '${action}' submitted successfully.` });
      setIsEditingDraft(false);
      await loadJob(false);
    } catch (err) {
      if (err.detail?.code === 'needs_acknowledgement') {
        setAlert({
          type: 'warning',
          message: 'Edits contain unverified claims. Check the acknowledgement box to confirm your override.',
        });
      } else {
        setAlert({ type: 'error', message: err.message || 'Decision failed.' });
      }
    } finally {
      setActionLoading(false);
    }
  }

  async function handleRetry() {
    setActionLoading(true);
    setAlert(null);
    try {
      await api.retryJob(jobId);
      setAlert({ type: 'success', message: 'Workflow retrying from last checkpoint in background.' });
      await loadJob(false);
    } catch (err) {
      setAlert({ type: 'error', message: err.message || 'Failed to retry job.' });
    } finally {
      setActionLoading(false);
    }
  }

  async function handleRematch() {
    setActionLoading(true);
    setAlert(null);
    try {
      await api.rematchJob(jobId);
      setAlert({ type: 'success', message: 'Fresh rematch and tailoring run started in background.' });
      await loadJob(false);
    } catch (err) {
      setAlert({ type: 'error', message: err.message || 'Failed to rematch job.' });
    } finally {
      setActionLoading(false);
    }
  }

  async function handlePatchStatus(newStatus) {
    setActionLoading(true);
    setAlert(null);
    try {
      await api.updateJobStatus(jobId, newStatus);
      setAlert({ type: 'success', message: `Status updated to '${newStatus}'.` });
      await loadJob(false);
    } catch (err) {
      setAlert({ type: 'error', message: err.message || 'Failed to update status.' });
    } finally {
      setActionLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="py-20 text-center text-slate-400 text-sm">
        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-emerald-600" />
        Loading application details...
      </div>
    );
  }

  if (!job) {
    return (
      <div className="py-20 text-center text-slate-500">
        <p>Job not found.</p>
        <button onClick={onBack} className="mt-3 text-emerald-600 font-medium text-xs hover:underline">
          Return to Jobs Board
        </button>
      </div>
    );
  }

  const match = job.match;
  const draft = job.draft;
  const pendingInterrupt = job.pending_interrupt;
  const wordCount = editedCoverNote ? editedCoverNote.trim().split(/\s+/).length : 0;

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-12">
      {/* Back Button & Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <button
            onClick={onBack}
            className="text-xs text-slate-500 hover:text-slate-800 flex items-center gap-1 mb-2 font-medium transition"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Board
          </button>
          <h1 className="text-2xl font-bold text-slate-900">{job.title || 'Unknown Opportunity'}</h1>
          <p className="text-sm text-slate-600">
            {job.company || 'Unknown Company'} • {job.location || 'Location Not Specified'} •{' '}
            {job.duration_months ? `${job.duration_months} Months` : 'Duration Not Specified'}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right">
            <span className="text-[10px] uppercase font-bold text-slate-400 block tracking-wider">Status</span>
            <span className="px-3 py-1 text-xs rounded-full font-semibold capitalize inline-block bg-slate-900 text-white">
              {job.status?.replace(/_/g, ' ')}
            </span>
          </div>
          {['processing', 'drafting'].includes(job.status) && (
            <RefreshCw className="w-5 h-5 text-emerald-600 animate-spin" />
          )}
        </div>
      </div>

      {alert && (
        <div
          className={`p-4 rounded-lg flex items-start gap-3 ${
            alert.type === 'success'
              ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
              : alert.type === 'warning'
              ? 'bg-amber-50 text-amber-800 border border-amber-200'
              : 'bg-rose-50 text-rose-800 border border-rose-200'
          }`}
        >
          {alert.type === 'success' ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-600 mt-0.5 shrink-0" />
          ) : alert.type === 'warning' ? (
            <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" />
          ) : (
            <AlertCircle className="w-5 h-5 text-rose-600 mt-0.5 shrink-0" />
          )}
          <span className="text-sm font-medium">{alert.message}</span>
        </div>
      )}

      {/* Decision Action Callout Card (When Paused at Interrupt) */}
      {pendingInterrupt && (
        <div className="bg-amber-50 border-2 border-amber-300 rounded-xl p-5 shadow-xs space-y-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-6 h-6 text-amber-600 shrink-0 mt-0.5" />
            <div className="flex-1">
              <h3 className="font-bold text-amber-900 text-sm">
                Human Action Required: {pendingInterrupt.type?.replace(/_/g, ' ').toUpperCase()}
              </h3>
              <p className="text-xs text-amber-800 mt-1">
                {pendingInterrupt.type === 'confirm_tailoring' &&
                  `Match score (${pendingInterrupt.score}%) is below your auto-tailoring threshold. Decide whether to proceed with tailoring or skip this role.`}
                {pendingInterrupt.type === 'approval' &&
                  'Your tailored resume and cover note have been generated and passed verification checks. Review and give your final approval before applying.'}
                {pendingInterrupt.type === 'manual_edit_required' &&
                  'Draft verification flagged potential factual inflation or unverified skills. Review below, edit claims, or acknowledge override.'}
              </p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap gap-2 pt-2 border-t border-amber-200">
            {pendingInterrupt.type === 'confirm_tailoring' && (
              <>
                <button
                  type="button"
                  onClick={() => handleDecision('proceed')}
                  disabled={actionLoading}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition disabled:opacity-50"
                >
                  <Check className="w-4 h-4" /> Proceed to Tailor
                </button>
                <button
                  type="button"
                  onClick={() => handleDecision('skip')}
                  disabled={actionLoading}
                  className="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-semibold transition disabled:opacity-50"
                >
                  Skip Job
                </button>
              </>
            )}

            {pendingInterrupt.type === 'approval' && (
              <>
                <button
                  type="button"
                  onClick={() => handleDecision('approve')}
                  disabled={actionLoading}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition disabled:opacity-50"
                >
                  <CheckCircle2 className="w-4 h-4" /> Approve Application
                </button>
                <button
                  type="button"
                  onClick={() => handleDecision('reject')}
                  disabled={actionLoading}
                  className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition disabled:opacity-50"
                >
                  <XCircle className="w-4 h-4" /> Reject
                </button>
                <button
                  type="button"
                  onClick={() => setIsEditingDraft(!isEditingDraft)}
                  className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition"
                >
                  <Edit3 className="w-4 h-4" /> {isEditingDraft ? 'Cancel Edit' : 'Edit Draft'}
                </button>
              </>
            )}

            {pendingInterrupt.type === 'manual_edit_required' && (
              <div className="w-full space-y-3">
                <label className="flex items-center gap-2 text-xs font-semibold text-amber-900 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={acknowledgeWarnings}
                    onChange={(e) => setAcknowledgeWarnings(e.target.checked)}
                    className="rounded text-amber-600 focus:ring-amber-500"
                  />
                  I acknowledge unverified claim warnings and confirm my user override
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => handleDecision('submit_edits', true)}
                    disabled={actionLoading}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition disabled:opacity-50"
                  >
                    <Send className="w-4 h-4" /> Submit Edits & Proceed
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDecision('abandon')}
                    disabled={actionLoading}
                    className="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-semibold transition disabled:opacity-50"
                  >
                    Abandon Job
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Failure Recovery Card */}
      {job.status === 'failed' && (
        <div className="bg-rose-50 border border-rose-300 rounded-xl p-4 flex items-center justify-between">
          <div>
            <h3 className="text-xs font-bold text-rose-800">Workflow Paused on Failure</h3>
            <p className="text-xs text-rose-700 mt-0.5">{job.error || 'Execution encountered an unhandled error.'}</p>
          </div>
          <button
            type="button"
            onClick={handleRetry}
            disabled={actionLoading}
            className="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold rounded-lg flex items-center gap-1.5 transition"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Retry
          </button>
        </div>
      )}

      {/* Post-Approval Lifecycle & Export Controls */}
      {['approved', 'applied', 'interview'].includes(job.status) && (
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-600">Application Lifecycle:</span>
            {['applied', 'interview', 'closed'].map((targetStatus) => (
              <button
                key={targetStatus}
                onClick={() => handlePatchStatus(targetStatus)}
                disabled={actionLoading || job.status === targetStatus}
                className={`px-3 py-1 text-xs rounded-lg font-medium capitalize border transition ${
                  job.status === targetStatus
                    ? 'bg-emerald-600 text-white border-emerald-600'
                    : 'bg-slate-50 text-slate-600 hover:bg-slate-100 border-slate-200'
                }`}
              >
                Mark as {targetStatus}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <a
              href={api.getExportUrl(jobId, 'docx')}
              download
              className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition"
            >
              <Download className="w-3.5 h-3.5" /> Export DOCX
            </a>
            <a
              href={api.getExportUrl(jobId, 'md')}
              download
              className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold flex items-center gap-1.5 border border-slate-200 transition"
            >
              <Download className="w-3.5 h-3.5" /> Markdown
            </a>
          </div>
        </div>
      )}

      {/* Match Assessment Card */}
      {match && (
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h2 className="text-lg font-semibold text-slate-800">Match Assessment</h2>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">Overall Fit:</span>
              <span className="text-lg font-bold text-emerald-600">{match.score}%</span>
            </div>
          </div>

          {/* Breakdown Progress Bars */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
            <div>
              <div className="flex justify-between text-xs font-medium text-slate-600 mb-1">
                <span>Required Skills (50%)</span>
                <span>{match.matched_skills?.length || 0} / {job.required_skills?.length || 0}</span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 rounded-full"
                  style={{
                    width: `${job.required_skills?.length ? (match.matched_skills.length / job.required_skills.length) * 100 : 0}%`,
                  }}
                />
              </div>
            </div>

            <div>
              <div className="flex justify-between text-xs font-medium text-slate-600 mb-1">
                <span>Project Semantic (30%)</span>
                <span>
                  {match.score_breakdown?.calibrated_similarity
                    ? `${Math.round(match.score_breakdown.calibrated_similarity * 100)}%`
                    : '—'}
                </span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-500 rounded-full"
                  style={{
                    width: `${match.score_breakdown?.calibrated_similarity ? match.score_breakdown.calibrated_similarity * 100 : 0}%`,
                  }}
                />
              </div>
            </div>

            <div>
              <div className="flex justify-between text-xs font-medium text-slate-600 mb-1">
                <span>Preference Fit (20%)</span>
                <span>
                  {match.score_breakdown?.preference_score !== undefined
                    ? `${Math.round(match.score_breakdown.preference_score)}%`
                    : '100%'}
                </span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-teal-500 rounded-full"
                  style={{
                    width: `${match.score_breakdown?.preference_score !== undefined ? match.score_breakdown.preference_score : 100}%`,
                  }}
                />
              </div>
            </div>
          </div>

          {/* Caps Callouts */}
          {match.score_breakdown?.cap_reasons?.length > 0 && (
            <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800 space-y-1">
              <span className="font-semibold block flex items-center gap-1">
                <ShieldAlert className="w-3.5 h-3.5 text-amber-600" /> Score Caps Applied:
              </span>
              {match.score_breakdown.cap_reasons.map((r, i) => (
                <div key={i}>• {r}</div>
              ))}
            </div>
          )}

          {/* Match Reasoning */}
          {match.reasoning && (
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-700">
              <span className="font-semibold text-slate-900 block mb-1">Reasoning Analysis:</span>
              <p>{match.reasoning}</p>
            </div>
          )}

          {['saved', 'skipped', 'failed'].includes(job.status) && (
            <div className="pt-2 flex justify-end">
              <button
                type="button"
                onClick={handleRematch}
                disabled={actionLoading}
                className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition"
              >
                <RefreshCw className="w-3.5 h-3.5" /> Rematch & Retailor
              </button>
            </div>
          )}
        </div>
      )}

      {/* Tailored Application Drafts Section */}
      {draft && (
        <div className="space-y-6">
          <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-6">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h2 className="text-lg font-semibold text-slate-800">Tailored Application Draft</h2>
              {draft.user_override && (
                <span className="px-2.5 py-0.5 bg-amber-100 text-amber-800 border border-amber-300 text-[11px] rounded-full font-semibold">
                  User Override Recorded
                </span>
              )}
            </div>

            {/* Skills Comparison */}
            <div>
              <h3 className="text-xs font-bold uppercase text-slate-500 mb-2 tracking-wider">
                Tailored Skills Section
              </h3>
              {isEditingDraft ? (
                <input
                  type="text"
                  value={editedSkills}
                  onChange={(e) => setEditedSkills(e.target.value)}
                  className="w-full p-2.5 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {draft.tailored_resume?.skills_section?.map((skill, idx) => (
                    <span
                      key={idx}
                      className="px-2.5 py-1 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-md text-xs font-medium"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Project Bullets */}
            <div>
              <h3 className="text-xs font-bold uppercase text-slate-500 mb-2 tracking-wider">
                Tailored Project Experience
              </h3>
              <div className="space-y-4">
                {draft.tailored_resume?.project_bullets?.map((pb, pIdx) => (
                  <div key={pIdx} className="p-3.5 bg-slate-50 border border-slate-200 rounded-lg">
                    <h4 className="font-semibold text-xs text-slate-800 mb-2">{pb.project_title}</h4>
                    <ul className="list-disc list-inside text-xs text-slate-600 space-y-1">
                      {pb.bullets?.map((b, bIdx) => (
                        <li key={bIdx}>{b}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>

            {/* Cover Note */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-bold uppercase text-slate-500 tracking-wider">
                  Factual Cover Note
                </h3>
                <span className={`text-xs ${wordCount >= 120 && wordCount <= 180 ? 'text-emerald-600 font-semibold' : 'text-slate-400'}`}>
                  {wordCount} words (Target: 120-180)
                </span>
              </div>

              {isEditingDraft ? (
                <textarea
                  rows={6}
                  value={editedCoverNote}
                  onChange={(e) => setEditedCoverNote(e.target.value)}
                  className="w-full p-3 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 leading-relaxed"
                />
              ) : (
                <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-700 whitespace-pre-wrap leading-relaxed">
                  {draft.cover_note?.text}
                </div>
              )}
            </div>

            {/* Verification Audit Report */}
            {draft.verification_result && (
              <div className="pt-4 border-t border-slate-100 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase text-slate-500 tracking-wider">
                    Verification Audit Report
                  </h3>
                  <span
                    className={`px-2.5 py-0.5 text-xs font-semibold rounded-full border ${
                      draft.verification_result.passed
                        ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                        : 'bg-rose-50 text-rose-800 border-rose-200'
                    }`}
                  >
                    {draft.verification_result.passed ? 'All Checks Passed' : 'Verification Flagged'}
                  </span>
                </div>

                {draft.verification_result.unsupported_claims?.length > 0 && (
                  <div className="space-y-2">
                    <span className="text-xs font-semibold text-rose-700 block">
                      Unsupported / Inflated Claims Flagged:
                    </span>
                    {draft.verification_result.unsupported_claims.map((claim, cIdx) => (
                      <div
                        key={cIdx}
                        className="p-3 bg-rose-50/60 border border-rose-200 rounded-lg text-xs text-rose-900 space-y-0.5"
                      >
                        <div className="font-semibold">
                          [{claim.layer}] {claim.claim}
                        </div>
                        <div className="text-rose-700">{claim.reason}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

