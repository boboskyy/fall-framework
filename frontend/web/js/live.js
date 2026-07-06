// live.js — live evaluation progress channel.
// Prefers the gateway SSE stream (staged endpoint). If that endpoint isn't
// deployed yet (404 / connection error before any event), it transparently
// falls back to polling /status (+ /progress if available). This means the UI
// is live TODAY against the currently-running gateway, and auto-upgrades to
// server-push once the SSE-enabled gateway is redeployed.
import { api } from './api.js';

const DONE = new Set(['completed', 'failed', 'cancelled', 'partial']);

export function watchEvaluation(evalId, { onUpdate, onDone, interval = 1200 } = {}) {
  let stopped = false;
  let es = null;
  let timer = null;
  let gotEvent = false;
  let progressGone = false;   // once /progress 404s it won't appear without redeploy

  const emit = (s) => {
    if (stopped || !s) return;
    onUpdate && onUpdate(s);
    if (DONE.has(s.status)) { stop(); onDone && onDone(s); }
  };

  async function pollOnce() {
    if (stopped) return;
    try {
      const status = await api.evalStatus(evalId);
      let detail = null;
      if (!progressGone) {
        try { detail = await api.evalProgress(evalId); }
        catch (e) { if (e.status === 404) progressGone = true; }   // staged endpoint absent → stop probing
      }
      emit(detail ? { ...status, ...detail } : status);
    } catch (e) { /* transient */ }
  }
  function startPolling() {
    pollOnce();
    timer = setInterval(pollOnce, interval);
  }

  function startSSE() {
    try { es = new EventSource(api.streamUrl(evalId)); }
    catch { startPolling(); return; }
    es.onmessage = (ev) => {
      gotEvent = true;
      try { emit(JSON.parse(ev.data)); } catch {}
    };
    es.addEventListener('done', (ev) => { try { emit(JSON.parse(ev.data)); } catch {} });
    es.onerror = () => {
      es.close();
      if (!gotEvent && !stopped) startPolling();   // endpoint not there → poll
    };
  }

  function stop() {
    stopped = true;
    if (es) es.close();
    if (timer) clearInterval(timer);
  }

  startSSE();
  return stop;
}
