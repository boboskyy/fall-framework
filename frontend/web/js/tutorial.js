// tutorial.js — persistent, navigation-only guided tour. Pulses the current
// target element (amber) with a coach bar; advances when the user clicks it.
// Progress index is kept in localStorage (NOT the URL); on reload only the
// current step's highlight remains. Steps are an editable array.
import { parse, go } from './router.js';
import { t } from './i18n.js';
import { toast } from './components.js';

const KEY = 'fallfw_tut';
const DONE = KEY + '_done';

// route: page path where the target lives (null = any page, e.g. top nav).
// sel: CSS selector for the target. event: 'click' (default) | 'change'.
const STEPS = [
  { route: '/',           sel: '#ds-sel',                              text: 'tut_dataset' },
  { route: '/',           sel: '#lab-tabs a[href*="/threshold"]',      text: 'tut_threshold' },
  { route: '/threshold',  sel: '#th a.btn.ghost',                      text: 'tut_back' },
  { route: '/',           sel: '#lab-tabs a[href*="/diversity"]',      text: 'tut_diversity' },
  { route: '/diversity',  sel: '#dv a.btn.ghost',                      text: 'tut_back' },
  { route: '/',           sel: '#lab-tabs a[href*="/files"]',          text: 'tut_clips' },
  { route: '/files',      sel: '#tb tr.clip-row',                      text: 'tut_expand' },
  { route: '/files',      sel: '.exp-row a[href*="/eval"]',            text: 'tut_evallink' },
  { route: '/eval',       sel: '.badge.info[href*="ds="]',             text: 'tut_tag' },
  { route: null,          sel: '#nav a[href$="/evaluate"]',            text: 'tut_nav_eval' },
  { route: null,          sel: '#nav a[href$="/matrix"]',             text: 'tut_nav_matrix' },
  { route: null,          sel: '#nav a[href$="/datasets"]',           text: 'tut_nav_datasets' },
  { route: null,          sel: '#nav a[href$="/detectors"]',          text: 'tut_nav_detectors' },
  { route: '/detectors',  sel: '#d-body a[href*="boboskyy"]',          text: 'tut_boboskyy' },
  { route: null,          sel: '#sysbar',                              text: 'tut_drawer' },
];

let idx = (() => { try { const v = parseInt(localStorage.getItem(KEY), 10); return Number.isFinite(v) ? v : 0; } catch { return 0; } })();
let pulsedEl = null, pulsedIdx = -1, scheduled = false, clickH = null, changeH = null;

const save = () => { try { localStorage.setItem(KEY, String(idx)); } catch {} };

function clearPulse() {
  if (pulsedEl) {
    pulsedEl.classList.remove('tut-pulse');
    if (clickH) pulsedEl.removeEventListener('click', clickH, true);
    if (changeH) pulsedEl.removeEventListener('change', changeH);
  }
  pulsedEl = null; pulsedIdx = -1; clickH = null; changeH = null;
  document.querySelectorAll('.tut-pulse').forEach(e => e.classList.remove('tut-pulse'));
  const c = document.getElementById('tut-coach');
  if (c) c.remove();
}

function showCoach(textKey) {
  let c = document.getElementById('tut-coach');
  if (!c) { c = document.createElement('div'); c.id = 'tut-coach'; c.className = 'tut-coach'; document.body.appendChild(c); }
  c.innerHTML = `<span class="tstep">${t('tut_title')} · ${idx + 1}/${STEPS.length}</span>`
    + `<span>${t(textKey)}</span><span class="tskip">${t('tut_skip')}</span>`;
  c.querySelector('.tskip').addEventListener('click', () => { idx = STEPS.length; save(); finish(); });
}

function finish() {
  clearPulse();
  try { if (localStorage.getItem(DONE)) return; localStorage.setItem(DONE, '1'); } catch {}
  toast(t('tut_done'), 'ok', 6000);
}

function advance() { idx++; save(); clearPulse(); schedule(); }

function tryPulse() {
  if (idx >= STEPS.length) { finish(); return; }
  const cur = STEPS[idx];
  if (cur.route && parse().path !== cur.route) { clearPulse(); return; }
  const el = document.querySelector(cur.sel);
  if (el && el === pulsedEl && idx === pulsedIdx) return;   // already pulsing this one
  clearPulse();
  if (!el) return;                                          // not rendered yet → observer retries
  pulsedEl = el; pulsedIdx = idx;
  el.classList.add('tut-pulse');
  showCoach(cur.text);
  if (cur.event === 'change') {
    changeH = () => { if (!cur.when || cur.when(el)) advance(); };
    el.addEventListener('change', changeH);
  } else {
    clickH = () => advance();
    el.addEventListener('click', clickH, true);
  }
}

function schedule() { if (scheduled) return; scheduled = true; setTimeout(() => { scheduled = false; tryPulse(); }, 120); }

export function resetTutorial() {
  idx = 0;
  try { localStorage.removeItem(DONE); } catch {}
  save();
  clearPulse();
  document.body.classList.remove('drawer-open');   // close the System drawer
  go('/');                                          // step 1 lives on the Lab
  schedule();
}

export function initTutorial() {
  const main = document.getElementById('app-main');
  if (main) new MutationObserver(schedule).observe(main, { childList: true, subtree: true });
  window.addEventListener('resize', schedule);
  schedule();
}
export const refreshTutorial = () => schedule();
