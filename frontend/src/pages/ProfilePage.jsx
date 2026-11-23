import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { 
  Upload, FileText, CheckCircle2, AlertCircle, Save, 
  Briefcase, GraduationCap, Award, ExternalLink, Sliders 
} from 'lucide-react';

export default function ProfilePage() {
  const [profile, setProfile] = useState(null);
  const [preferences, setPreferences] = useState(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [alert, setAlert] = useState(null);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [profData, prefData] = await Promise.allSettled([
        api.getProfile(),
        api.getPreferences(),
      ]);

      if (profData.status === 'fulfilled') {
        setProfile(profData.value);
      } else {
        setProfile(null);
      }

      if (prefData.status === 'fulfilled') {
        setPreferences(prefData.value);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleFileUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      setAlert({ type: 'error', message: 'File is too large. Maximum size is 5 MB.' });
      return;
    }

    setUploading(true);
    setAlert(null);
    try {
      const res = await api.uploadResume(file);
      setProfile(res);
      setAlert({ type: 'success', message: 'Resume uploaded and parsed successfully!' });
    } catch (err) {
      setAlert({ type: 'error', message: err.message || 'Failed to upload resume.' });
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  }

  async function handleSaveProfile(e) {
    e.preventDefault();
    if (!profile) return;
    setSavingProfile(true);
    setAlert(null);
    try {
      const res = await api.updateProfile(profile);
      setProfile(res);
      setAlert({ type: 'success', message: 'Profile updated successfully.' });
    } catch (err) {
      setAlert({ type: 'error', message: err.message || 'Failed to save profile.' });
    } finally {
      setSavingProfile(false);
    }
  }

  async function handleSavePreferences(e) {
    e.preventDefault();
    if (!preferences) return;
    setSavingPrefs(true);
    setAlert(null);
    try {
      const res = await api.updatePreferences(preferences);
      setPreferences(res);
      setAlert({ type: 'success', message: 'Preferences updated successfully.' });
    } catch (err) {
      setAlert({ type: 'error', message: err.message || 'Failed to update preferences.' });
    } finally {
      setSavingPrefs(false);
    }
  }

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Candidate Profile & Preferences</h1>
        <p className="text-slate-500 mt-1">
          Upload your resume to extract candidate facts, then configure matching thresholds and preferences.
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

      {/* Resume Upload Card */}
      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-800 mb-2 flex items-center gap-2">
          <Upload className="w-5 h-5 text-emerald-600" />
          Resume Upload
        </h2>
        <p className="text-sm text-slate-500 mb-4">
          Supported formats: PDF and DOCX (up to 5 MB). Parsing extracts skills, education, and project facts without hallucination.
        </p>

        <label className="border-2 border-dashed border-slate-300 hover:border-emerald-500 hover:bg-emerald-50/20 rounded-xl p-8 flex flex-col items-center justify-center cursor-pointer transition">
          <FileText className="w-10 h-10 text-slate-400 mb-2" />
          <span className="text-sm font-medium text-slate-700">
            {uploading ? 'Parsing resume...' : 'Click or drag resume file here'}
          </span>
          <span className="text-xs text-slate-400 mt-1">PDF or DOCX text-based resumes</span>
          <input
            type="file"
            className="hidden"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={handleFileUpload}
            disabled={uploading}
          />
        </label>
      </div>

      {/* Grid: Parsed Profile & Preferences */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Profile Card (2 cols) */}
        <div className="lg:col-span-2 bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-6">
          <div className="flex items-center justify-between border-b border-slate-100 pb-4">
            <h2 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
              <Briefcase className="w-5 h-5 text-emerald-600" />
              Candidate Profile Facts
            </h2>
            {profile && (
              <button
                type="button"
                onClick={handleSaveProfile}
                disabled={savingProfile}
                className="px-3 py-1.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg flex items-center gap-1.5 transition disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                {savingProfile ? 'Saving...' : 'Save Changes'}
              </button>
            )}
          </div>

          {loading ? (
            <div className="text-center py-12 text-slate-400 text-sm">Loading profile data...</div>
          ) : !profile ? (
            <div className="text-center py-12 text-slate-400 text-sm">
              No profile found. Please upload a resume above to populate candidate facts.
            </div>
          ) : (
            <form className="space-y-6">
              {/* Name */}
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1">Candidate Name</label>
                <input
                  type="text"
                  value={profile.name || ''}
                  onChange={(e) => setProfile({ ...profile, name: e.target.value })}
                  className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              {/* Skills */}
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1">
                  Extracted Skills ({profile.skills?.length || 0})
                </label>
                <div className="flex flex-wrap gap-1.5 mb-2 p-2 bg-slate-50 border border-slate-200 rounded-lg max-h-36 overflow-y-auto">
                  {profile.skills?.map((s, idx) => (
                    <span
                      key={idx}
                      className="px-2 py-1 bg-white text-slate-700 border border-slate-200 text-xs rounded font-medium shadow-2xs"
                    >
                      {s}
                    </span>
                  ))}
                </div>
                <input
                  type="text"
                  placeholder="Comma separated skills to update list..."
                  value={profile.skills?.join(', ') || ''}
                  onChange={(e) =>
                    setProfile({
                      ...profile,
                      skills: e.target.value.split(',').map((x) => x.trim()).filter(Boolean),
                    })
                  }
                  className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              {/* Projects */}
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-2">
                  Projects ({profile.projects?.length || 0})
                </label>
                <div className="space-y-3">
                  {profile.projects?.map((proj, pIdx) => (
                    <div key={pIdx} className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-sm text-slate-800">{proj.title}</span>
                        {proj.link && (
                          <a
                            href={proj.link}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-emerald-600 flex items-center gap-1 hover:underline"
                          >
                            Link <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {proj.tech?.map((t, tIdx) => (
                          <span key={tIdx} className="px-1.5 py-0.5 text-[10px] bg-slate-200 text-slate-700 rounded">
                            {t}
                          </span>
                        ))}
                      </div>
                      <ul className="list-disc list-inside text-xs text-slate-600 space-y-0.5 mt-1">
                        {proj.bullets?.map((b, bIdx) => (
                          <li key={bIdx}>{b}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>

              {/* Education & Experience Summary */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-600 mb-1 flex items-center gap-1">
                    <GraduationCap className="w-4 h-4 text-slate-400" /> Education
                  </label>
                  <div className="text-xs text-slate-600 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
                    {profile.education?.length ? (
                      profile.education.map((edu, idx) => (
                        <div key={idx} className="mb-1">
                          <p className="font-medium text-slate-800">{edu.institution}</p>
                          <p>{edu.degree} in {edu.field}</p>
                          {edu.cgpa && <p className="text-slate-500">CGPA: {edu.cgpa}</p>}
                        </div>
                      ))
                    ) : (
                      <span className="text-slate-400">None listed</span>
                    )}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-600 mb-1 flex items-center gap-1">
                    <Award className="w-4 h-4 text-slate-400" /> Experience
                  </label>
                  <div className="text-xs text-slate-600 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
                    {profile.experience?.length ? (
                      profile.experience.map((exp, idx) => (
                        <div key={idx} className="mb-1">
                          <p className="font-medium text-slate-800">{exp.company} — {exp.role}</p>
                          <p className="text-slate-500">{exp.start_date} to {exp.end_date || 'Present'}</p>
                        </div>
                      ))
                    ) : (
                      <span className="text-slate-400">None listed</span>
                    )}
                  </div>
                </div>
              </div>
            </form>
          )}
        </div>

        {/* Preferences Card (1 col) */}
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-5">
          <div className="flex items-center justify-between border-b border-slate-100 pb-4">
            <h2 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
              <Sliders className="w-5 h-5 text-emerald-600" />
              Preferences
            </h2>
            {preferences && (
              <button
                type="button"
                onClick={handleSavePreferences}
                disabled={savingPrefs}
                className="px-3 py-1.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg flex items-center gap-1.5 transition disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                {savingPrefs ? 'Saving...' : 'Save'}
              </button>
            )}
          </div>

          {!preferences ? (
            <div className="text-xs text-slate-400 py-6 text-center">Loading preferences...</div>
          ) : (
            <form className="space-y-4 text-xs">
              {/* Target Roles */}
              <div>
                <label className="block font-semibold text-slate-600 mb-1">Target Roles</label>
                <input
                  type="text"
                  value={preferences.target_roles?.join(', ') || ''}
                  onChange={(e) =>
                    setPreferences({
                      ...preferences,
                      target_roles: e.target.value.split(',').map((x) => x.trim()).filter(Boolean),
                    })
                  }
                  className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  placeholder="e.g. Software Engineer Intern, Backend Intern"
                />
              </div>

              {/* Max Duration */}
              <div>
                <label className="block font-semibold text-slate-600 mb-1">
                  Max Duration (Months): {preferences.max_duration_months}
                </label>
                <input
                  type="number"
                  min="1"
                  max="24"
                  value={preferences.max_duration_months || 6}
                  onChange={(e) =>
                    setPreferences({
                      ...preferences,
                      max_duration_months: parseInt(e.target.value, 10) || 6,
                    })
                  }
                  className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              {/* Locations & Remote */}
              <div>
                <label className="block font-semibold text-slate-600 mb-1">Preferred Locations</label>
                <input
                  type="text"
                  value={preferences.preferred_locations?.join(', ') || ''}
                  onChange={(e) =>
                    setPreferences({
                      ...preferences,
                      preferred_locations: e.target.value.split(',').map((x) => x.trim()).filter(Boolean),
                    })
                  }
                  className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 mb-2"
                  placeholder="e.g. Austin, TX, San Francisco, CA"
                />
                <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-700">
                  <input
                    type="checkbox"
                    checked={preferences.remote_ok}
                    onChange={(e) =>
                      setPreferences({ ...preferences, remote_ok: e.target.checked })
                    }
                    className="rounded text-emerald-600 focus:ring-emerald-500"
                  />
                  Remote OK
                </label>
              </div>

              {/* Avoid Skills */}
              <div>
                <label className="block font-semibold text-slate-600 mb-1">Avoid Skills (Hard Penalty)</label>
                <input
                  type="text"
                  value={preferences.avoid_skills?.join(', ') || ''}
                  onChange={(e) =>
                    setPreferences({
                      ...preferences,
                      avoid_skills: e.target.value.split(',').map((x) => x.trim()).filter(Boolean),
                    })
                  }
                  className="w-full px-2.5 py-1.5 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  placeholder="e.g. PHP, WordPress"
                />
              </div>

              {/* Thresholds */}
              <div className="pt-2 border-t border-slate-100 space-y-3">
                <div>
                  <div className="flex justify-between font-semibold text-slate-600 mb-1">
                    <span>Min Score to Consider</span>
                    <span className="text-emerald-600">{preferences.min_score_to_consider}%</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="99"
                    value={preferences.min_score_to_consider}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10);
                      if (val < preferences.min_score_to_tailor) {
                        setPreferences({ ...preferences, min_score_to_consider: val });
                      }
                    }}
                    className="w-full accent-emerald-600"
                  />
                  <span className="text-[10px] text-slate-400">Jobs below this score are auto-skipped.</span>
                </div>

                <div>
                  <div className="flex justify-between font-semibold text-slate-600 mb-1">
                    <span>Min Score to Auto-Tailor</span>
                    <span className="text-emerald-600">{preferences.min_score_to_tailor}%</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="100"
                    value={preferences.min_score_to_tailor}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10);
                      if (val > preferences.min_score_to_consider) {
                        setPreferences({ ...preferences, min_score_to_tailor: val });
                      }
                    }}
                    className="w-full accent-emerald-600"
                  />
                  <span className="text-[10px] text-slate-400">Jobs below this pause for tailoring confirmation.</span>
                </div>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

