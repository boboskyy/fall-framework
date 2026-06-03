// api.js — gateway REST client.
// Base resolves to (in priority): ?api= query → localStorage → relative /api/v1
// (relative works behind the nginx proxy that fronts the gateway).
function normalize(b) {
  b = b.replace(/\/$/, '');
  // accept either a full API base (…/api/v1) or a bare gateway root
  if (!/\/api(\/|$)/.test(b)) b += '/api/v1';
  return b;
}
function resolveBase() {
  const q = new URLSearchParams(location.search).get('api');
  if (q) { const b = normalize(q); try { localStorage.setItem('fallfw_api', b); } catch {} return b; }
  try { const s = localStorage.getItem('fallfw_api'); if (s) return normalize(s); } catch {}
  return '/api/v1';
}
export const BASE = resolveBase();

async function req(path, opts = {}) {
  const r = await fetch(BASE + path, {
    headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
    ...opts,
  });
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    const msg = (body && body.message) || (body && body.error) || r.status;
    throw Object.assign(new Error(msg), { status: r.status, body });
  }
  return body;
}

export const api = {
  base: BASE,
  config: () => req('/config'),
  // health / detectors
  health: () => req('/health'),
  detectors: (refresh = false) => req('/detectors' + (refresh ? '?refresh=true' : '')),
  detector: (n) => req(`/detectors/${n}`),
  detectorHealth: (n) => req(`/detectors/${n}/health`),
  detectorsSummary: () => req('/detectors/summary'),
  detectorStats: (n) => req(`/detectors/${n}/stats`),
  startDetector: (n) => req(`/detectors/${n}/start`, { method: 'POST' }),
  stopDetector: (n) => req(`/detectors/${n}/stop`, { method: 'POST' }),
  buildDetector: (n, device = 'cpu') => req(`/detectors/${n}/build`, { method: 'POST', body: JSON.stringify({ device }) }),
  rescanDetectors: () => req('/detectors/rescan', { method: 'POST' }),
  downloadDetector: (n) => req(`/detectors/${n}/download`, { method: 'POST', body: JSON.stringify({}) }),
  templateUrl: (name, category = 'object_detection', input = 'video') =>
    `${BASE}/template?name=${encodeURIComponent(name)}&category=${category}&input_type=${input}`,
  // datasets
  datasets: () => req('/datasets'),
  refreshRegistry: () => req('/datasets/refresh-registry', { method: 'POST' }),
  downloadDataset: (n) => req(`/datasets/${n}/download`, { method: 'POST' }),
  async uploadDataset(file, name) {
    const fd = new FormData();
    fd.append('file', file);
    if (name) fd.append('name', name);
    const r = await fetch(BASE + '/datasets/upload', { method: 'POST', body: fd });
    const b = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(b.message || b.error || r.status), { status: r.status });
    return b;
  },
  dataset: (n) => req(`/datasets/${n}`),
  datasetFiles: (n, perPage = 2000) => req(`/datasets/${n}/files?per_page=${perPage}`),
  // evaluations
  evaluations: () => req('/evaluations'),
  evalStatus: (id) => req(`/evaluate/${id}/status`),
  evalResults: (id) => req(`/evaluate/${id}/results`),
  evalProgress: (id) => req(`/evaluate/${id}/progress`),     // staged endpoint (per-detector); 404 until gateway redeploy
  startEval: (payload) => req('/evaluate', { method: 'POST', body: JSON.stringify(payload) }),
  cancelEval: (id) => req(`/evaluate/${id}/cancel`, { method: 'POST' }),
  exportUrl: (id, fmt = 'csv') => `${BASE}/evaluate/${id}/export?format=${fmt}`,
  streamUrl: (id) => `${BASE}/evaluate/${id}/stream`,         // SSE (staged); falls back to polling
};
