/**
 * API client library for Job-Search Copilot backend.
 */

const BASE_URL = '';

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const headers = options.headers || {};

  if (!(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const res = await fetch(url, { ...options, headers });
  
  if (!res.ok) {
    let errorDetail = res.statusText;
    try {
      const errorJson = await res.json();
      errorDetail = errorJson.detail || errorJson.message || JSON.stringify(errorJson);
    } catch {
      // Ignore parse failure, keep statusText
    }
    const err = new Error(typeof errorDetail === 'object' ? JSON.stringify(errorDetail) : errorDetail);
    err.status = res.status;
    err.detail = errorDetail;
    throw err;
  }

  // Handle blob or text responses
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return await res.json();
  }
  return res;
}

export const api = {
  // Health
  getHealth: () => request('/health'),

  // Profile & Preferences
  getProfile: () => request('/profile'),
  uploadResume: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return request('/profile/upload', {
      method: 'POST',
      body: formData,
    });
  },
  updateProfile: (profile) =>
    request('/profile', {
      method: 'PUT',
      body: JSON.stringify(profile),
    }),
  getPreferences: () => request('/preferences'),
  updatePreferences: (preferences) =>
    request('/preferences', {
      method: 'PUT',
      body: JSON.stringify(preferences),
    }),

  // Jobs
  getJobs: () => request('/jobs'),
  createJob: (payload) =>
    request('/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getJobDetail: (jobId) => request(`/jobs/${jobId}`),
  submitDecision: (jobId, decisionPayload) =>
    request(`/jobs/${jobId}/decision`, {
      method: 'POST',
      body: JSON.stringify(decisionPayload),
    }),
  retryJob: (jobId) =>
    request(`/jobs/${jobId}/retry`, {
      method: 'POST',
    }),
  rematchJob: (jobId) =>
    request(`/jobs/${jobId}/rematch`, {
      method: 'POST',
    }),
  updateJobStatus: (jobId, status) =>
    request(`/jobs/${jobId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),

  // Logs
  getLogs: (jobId = null, limit = 100) => {
    const query = jobId ? `?job_id=${encodeURIComponent(jobId)}&limit=${limit}` : `?limit=${limit}`;
    return request(`/logs${query}`);
  },

  // Export
  getExportUrl: (jobId, format = 'docx') => `/export/${jobId}?format=${format}`,
};

