// app.js — shell, navigation, language, system drawer, routing.
import { route, start, onChange, href, parse, setNotFound } from './router.js';
import { t, lang, setLang, onLang } from './i18n.js';
import { theme, setTheme } from './theme.js';
import { api } from './api.js';
import { loadConfig, isPreview } from './config.js';
import { initTutorial, refreshTutorial } from './tutorial.js';
import { qs, qsa, esc, healthBadge } from './components.js';

import * as lab from './views/lab.js';
import * as threshold from './views/threshold.js';
import * as diversity from './views/diversity.js';
import * as files from './views/files.js';
import * as matrix from './views/matrix.js';
import * as evaluate from './views/evaluate.js';
import * as evalView from './views/eval.js';
import * as detectors from './views/detectors.js';
import * as datasets from './views/datasets.js';
import * as system from './views/system.js';

const NAV = [
  { path: '/', key: 'nav_lab' },
  { path: '/evaluate', key: 'nav_evaluate' },
  { path: '/matrix', key: 'nav_matrix' },
  { path: '/detectors', key: 'nav_detectors' },
  { path: '/datasets', key: 'nav_datasets' },
];

function shell() {
  const root = qs('#root');
  root.className = 'app';
  root.innerHTML = `
    <header class="topbar">
      <a class="brand" href="${href('/')}"><span class="p">&gt;_</span>fallfw<span class="slash">/</span><span class="seg" id="brand-seg">lab</span></a>
      <nav class="nav" id="nav"></nav>
      <div class="topbar-right">
        <span id="preview-badge"></span>
        <div class="lang" id="theme" aria-label="theme">
          <button data-th="dark" title="dark theme">☾&nbsp;DARK</button><span class="sep">/</span><button data-th="light" title="light theme">☼&nbsp;LIGHT</button>
        </div>
        <div class="lang" id="lang">
          <button data-l="pl">PL</button><span class="sep">/</span><button data-l="en">EN</button>
        </div>
      </div>
    </header>
    <main class="main" id="app-main"></main>
    <footer class="foot">Fall FW - Karol Bobowski</footer>
    <div class="sysbar" id="sysbar" role="button" tabindex="0" aria-expanded="false" aria-controls="drawer" aria-label="system panel">
      <span id="sys-summary">${esc(t('system'))}: …</span>
      <span class="grow"></span>
      <span class="chev">▴</span>
    </div>
    <div class="drawer" id="drawer"><div class="drawer-inner" id="drawer-inner"></div></div>`;

  renderNav();
  qsa('#lang button').forEach(b => b.addEventListener('click', () => setLang(b.dataset.l)));
  syncLang();
  qsa('#theme button').forEach(b => b.addEventListener('click', () => { setTheme(b.dataset.th); syncTheme(); }));
  syncTheme();

  const sysbar = qs('#sysbar');
  sysbar.addEventListener('click', toggleDrawer);
  sysbar.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleDrawer(); }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (document.body.classList.contains('drawer-open')) { setDrawer(false); return; }  // close drawer first
    const tag = (document.activeElement && document.activeElement.tagName) || '';
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;   // let form controls keep Esc
    history.back();                                       // otherwise Esc = back
  });
}

const A11Y_LABELS = { 'ds-sel': 'dataset', 'ds': 'dataset', 'filter': 'classification filter',
  'detf': 'detector filter', 'hist-det': 'histogram detector', 'thr': 'min_fall_frames threshold' };
function decorateA11y(root) {
  root.querySelectorAll('select, input[type=range]').forEach(el => {
    if (!el.getAttribute('aria-label')) el.setAttribute('aria-label', A11Y_LABELS[el.id] || el.id || 'control');
  });
}

function renderNav() {
  const cur = parse().path;
  qs('#nav').innerHTML = NAV.map(n =>
    `<a href="${href(n.path)}" class="${n.path === cur ? 'active' : ''}">${esc(t(n.key))}</a>`).join('');
}
function syncLang() { qsa('#lang button').forEach(b => b.classList.toggle('active', b.dataset.l === lang())); }
function syncTheme() { qsa('#theme button').forEach(b => b.classList.toggle('active', b.dataset.th === theme())); }
function renderPreviewBadge() {
  const el = qs('#preview-badge');
  if (el) el.innerHTML = isPreview() ? `<span class="badge warn"><span class="dotled"></span>${esc(t('preview'))}</span>` : '';
}

function setDrawer(open) {
  document.body.classList.toggle('drawer-open', open);
  qs('#sysbar').setAttribute('aria-expanded', open ? 'true' : 'false');
  qs('#sysbar .chev').textContent = open ? '▾' : '▴';
  if (open) {
    const inner = qs('#drawer-inner');
    inner.innerHTML = `<div class="drawer-head"><span class="grow"></span>
      <button class="btn ghost sm" id="drawer-close" aria-label="close">✕</button></div>
      <div id="drawer-body"></div>`;
    qs('#drawer-close').addEventListener('click', (e) => { e.stopPropagation(); setDrawer(false); });
    system.render(qs('#drawer-body'));   // re-render → fresh container health
  }
}
function toggleDrawer() { setDrawer(!document.body.classList.contains('drawer-open')); }

async function refreshSysbar() {
  const el = qs('#sys-summary');
  if (!el) return;
  try {
    const d = await api.detectors();
    const dets = d.detectors || [];
    const healthy = dets.filter(x => x.container_status === 'healthy').length;
    el.innerHTML = `${esc(t('system'))}: <span class="hl">${healthy}/${dets.length}</span> ${esc(t('healthy'))} · <span class="badge ok" style="margin-left:.3rem"><span class="dotled"></span>${esc(t('gateway_ok'))}</span>`;
  } catch {
    el.innerHTML = `${esc(t('system'))}: <span class="badge bad"><span class="dotled"></span>${esc(t('gateway_down'))}</span>`;
  }
}

const SEG = { '/': 'lab', '/threshold': 'threshold', '/diversity': 'diversity', '/files': 'clips',
              '/matrix': 'matrix', '/evaluate': 'evaluate', '/eval': 'eval', '/detectors': 'detectors', '/datasets': 'datasets' };

function bind(view) {
  return (params) => {
    const main = qs('#app-main');
    main.innerHTML = '';
    Promise.resolve(view.render(main, params))
      .then(() => decorateA11y(main))
      .catch(e => main.innerHTML = `<div class="empty"><span class="big">error</span>${esc(e.message || e)}</div>`);
    qs('#brand-seg').textContent = SEG[parse().path] || 'lab';
  };
}

route('/', bind(lab));
route('/threshold', bind(threshold));
route('/diversity', bind(diversity));
route('/files', bind(files));
route('/matrix', bind(matrix));
route('/evaluate', bind(evaluate));
route('/eval', bind(evalView));
route('/detectors', bind(detectors));
route('/datasets', bind(datasets));
setNotFound((p) => {
  qs('#app-main').innerHTML = `<div class="empty"><span class="big">404</span>${esc(p)}</div>`;
  qs('#brand-seg').textContent = '404';
});

onChange(() => { renderNav(); refreshTutorial(); if (document.body.classList.contains('drawer-open')) setDrawer(false); });
onLang(() => { renderNav(); syncLang(); renderPreviewBadge(); refreshSysbar(); const { path, params } = parse();
  const r = { '/': lab, '/threshold': threshold, '/diversity': diversity, '/files': files,
              '/matrix': matrix, '/evaluate': evaluate, '/eval': evalView, '/detectors': detectors, '/datasets': datasets }[path];
  if (r) bind(r)(params); });

shell();
(async () => { await loadConfig(); renderPreviewBadge(); start(); initTutorial(); })();
refreshSysbar();
setInterval(refreshSysbar, 15000);
