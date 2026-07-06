// views/lab.js — Leaderboard Lab (landing). Per-dataset detector ranking
// reconstructed from the gateway's single-detector evaluations.
import { getDatasets, getEvals, leaderboard, bestPerMetric, invalidate } from '../store.js';
import { dsLabel, shortName, dec, pct, roman, FAMILY_LABEL, ALL_DS } from '../format.js';
import { stripedBar } from '../charts.js';
import { qs, qsa, spinner, empty, esc } from '../components.js';
import { t } from '../i18n.js';
import { href, go } from '../router.js';
import { leakCategory, CAT } from '../leakage.js';

const rankGlyph = (i) => roman(i);
let _monitorStop = null;   // live running-tasks poller (one at a time)

function renderRunning(running) {
  return `<div class="running-panel section">
    <div class="run-head"><span class="run-dot"></span>${esc(t('running'))} · ${running.length}</div>
    ${running.map(e => {
      const p = e.progress_pct ?? (e.total_tasks ? e.completed_tasks / e.total_tasks * 100 : 0);
      return `<a class="run-row" href="${href('/eval', { id: e.eval_id })}">
        <span class="rn">${esc(dsLabel(e.dataset_name))} <span class="dim">${esc(e.detector_names.map(shortName).join(', '))}</span></span>
        ${stripedBar(p / 100, { cls: 'violet' })}
        <span class="rp">${dec(p, 0)}% · ${e.completed_tasks || 0}/${e.total_tasks ?? '?'}</span>
      </a>`;
    }).join('')}
  </div>`;
}

// Poll for running evals; show the panel + condense the leaderboard while any run.
function startMonitor(root, params) {
  let iv = null, hadRunning = false;
  const stop = () => { if (iv) clearInterval(iv); iv = null; };
  const tick = async () => {
    const runEl = document.querySelector('#lab-running');
    if (!runEl) { stop(); return; }                 // navigated away
    let evals;
    try { evals = await getEvals(true); } catch { return; }
    const running = evals.filter(e => e.status === 'pending' || e.status === 'running');
    const lb = document.querySelector('#lb-table .lb');
    if (running.length) {
      runEl.innerHTML = renderRunning(running);
      lb && lb.classList.add('condensed');
      hadRunning = true;
    } else {
      runEl.innerHTML = '';
      lb && lb.classList.remove('condensed');
      if (hadRunning) { hadRunning = false; stop(); invalidate(); render(root, params); }  // a task finished → refresh
    }
  };
  iv = setInterval(tick, 2000);
  tick();
  return stop;
}

async function pickDataset(params) {
  const evals = await getEvals();
  const byDs = {};
  for (const e of evals) {
    if (e.status === 'completed' || e.status === 'partial') {
      byDs[e.dataset_name] = byDs[e.dataset_name] || new Set();
      e.detector_names.forEach(d => byDs[e.dataset_name].add(d));
    }
  }
  const withEvals = Object.keys(byDs);
  if (params.ds === ALL_DS) return { ds: ALL_DS, withEvals, byDs };
  if (params.ds && byDs[params.ds]) return { ds: params.ds, withEvals, byDs };
  // default: dataset with most detectors evaluated
  const best = withEvals.sort((a, b) => byDs[b].size - byDs[a].size)[0];
  return { ds: best, withEvals, byDs };
}

export async function render(root, params) {
  if (_monitorStop) { _monitorStop(); _monitorStop = null; }
  root.innerHTML = `<div class="eyebrow"><span class="n">01</span>${esc(t('lab_h'))}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(t('lab_h'))}</h1>
    <p class="page-sub">${esc(t('lab_sub'))}</p>
    <div id="lab-body">${spinner('…')}</div>`;
  const body = qs('#lab-body', root);

  let ctx;
  try { ctx = await pickDataset(params); }
  catch (e) { body.innerHTML = empty(t('gateway_down'), String(e.message || e)); return; }

  if (!ctx.ds) {
    body.innerHTML = empty(t('no_evals_h'), t('no_evals_b')) +
      `<div class="btn-row mt"><a class="btn" href="${href('/evaluate')}">${esc(t('run_eval'))}</a></div>`;
    return;
  }

  // dataset selector
  const datasets = await getDatasets().catch(() => []);
  const allOpt = `<option value="${ALL_DS}" ${ctx.ds === ALL_DS ? 'selected' : ''}>${esc(dsLabel(ALL_DS))}</option>`;
  const opts = allOpt + ctx.withEvals.map(d =>
    `<option value="${d}" ${d === ctx.ds ? 'selected' : ''}>${esc(dsLabel(d))} · ${ctx.byDs[d].size} det</option>`).join('');

  body.innerHTML = `
    <div class="row between mb">
      <div class="select">
        <select id="ds-sel">${opts}</select>
      </div>
      <div class="btn-row" id="lab-tabs">
        <a class="btn ghost sm" href="${href('/threshold', { ds: ctx.ds })}">${esc(t('nav_threshold'))} →</a>
        <a class="btn ghost sm" href="${href('/diversity', { ds: ctx.ds })}">${esc(t('nav_diversity'))} →</a>
        <a class="btn ghost sm" href="${href('/files', { ds: ctx.ds })}">${esc(t('nav_files'))} →</a>
        <a class="btn ghost sm" href="${href('/matrix')}">${esc(t('nav_matrix'))} →</a>
      </div>
    </div>
    <div id="lb-stats"></div>
    <div id="lab-running"></div>
    <div id="lb-chips"></div>
    <div id="lb-table" class="section">${spinner('…')}</div>`;

  qs('#ds-sel', body).addEventListener('change', (e) => go(href('/', { ds: e.target.value }).slice(1)));

  const lb = await leaderboard(ctx.ds);
  if (!lb.rows.length) {
    qs('#lb-table', body).innerHTML = empty(t('no_evals_h'), t('no_evals_b'));
    qs('#lb-chips', body).innerHTML = '';
    return;
  }

  // dashboard summary strip
  const allEvals = await getEvals();
  const clips = Math.max(...lb.rows.map(r => r.summary.total_files));
  const gtPf = (lb.rows.find(r => !r.partial) || lb.rows[0]).perFile;
  const fall = gtPf.filter(r => r.ground_truth_fall === true).length;
  const adl = gtPf.filter(r => r.ground_truth_fall === false).length;
  const avgF1 = lb.rows.reduce((s, r) => s + r.f1, 0) / lb.rows.length;
  const stat = (k, v, sub = '') => `<div class="stat"><div class="k">${esc(k)}</div><div class="v small">${v}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ''}</div>`;
  qs('#lb-stats', body).innerHTML = `<div class="grid section" style="grid-template-columns:repeat(auto-fit,minmax(128px,1fr))">
    ${stat(t('detectors'), lb.rows.length)}
    ${stat(t('clips'), clips)}
    ${stat(t('lab_balance'), `${fall} / ${adl}`)}
    ${stat(t('lab_avgf1'), dec(avgF1))}
    ${stat(t('lab_evals_total'), allEvals.length)}
    ${stat(t('lab_datasets'), ctx.withEvals.length)}
  </div>`;

  const best = bestPerMetric(lb.rows);
  const chip = (k, label, det, val) => `
    <div class="stat ${k === 'f1' ? 'hl' : ''}">
      <div class="k">${esc(label)}</div>
      <div class="v">${val}</div>
      <div class="sub">${esc(det.short)} <span class="fam" style="display:inline-flex">${det.family}</span></div>
    </div>`;
  qs('#lb-chips', body).innerHTML = `<div class="grid cols-4 section">
    ${chip('f1', t('best_f1'), best.f1, dec(best.f1.f1))}
    ${chip('r', t('best_recall'), best.recall, dec(best.recall.recall))}
    ${chip('fpr', t('lowest_fpr'), best.fpr, dec(best.fpr.fpr))}
    ${chip('p', t('best_prec'), best.precision, dec(best.precision.precision))}
  </div>`;

  const maxF1 = Math.max(...lb.rows.map(r => r.f1));
  const rowsHtml = lb.rows.map((r, i) => {
    const isBest = i === 0;
    const cat = ctx.ds !== ALL_DS ? leakCategory(r.name, ctx.ds) : 'ood';
    const leakBadge = cat !== 'ood'
      ? `<span class="leak-badge ${CAT[cat].cls}" title="${esc(t(CAT[cat].tip))}">${esc(CAT[cat].short)}</span>` : '';
    return `<a class="lb-row ${isBest ? 'best' : ''}" href="${href('/files', { ds: ctx.ds, det: r.name })}">
      <div class="rank r${i + 1}">${rankGlyph(i + 1)}</div>
      <div class="lb-name" title="${esc(r.name)} · ${esc(FAMILY_LABEL[r.family] || '')}">
        <span class="fam">${r.family}</span><span class="nm">${esc(r.short)}</span>${leakBadge}
        ${r.partial ? '<span class="badge warn" style="margin-left:.4rem">partial</span>' : ''}
      </div>
      ${stripedBar(r.f1, { max: 1, best: isBest })}
      <div class="lb-val">${dec(r.f1)}<span class="secd num">R ${dec(r.recall, 2)} · FPR ${dec(r.fpr, 2)}</span></div>
    </a>`;
  }).join('');

  qs('#lb-table', body).innerHTML = `
    <h2 class="sec-h">${esc(t('ranking'))} · F1 <span class="rule"></span>
      <span class="meta">${esc(dsLabel(ctx.ds))} · ${lb.rows.length} ${esc(t('detectors'))} · ${Math.max(...lb.rows.map(r => r.summary.total_files))} ${esc(t('clips'))}</span></h2>
    <div class="panel"><div class="lb">${rowsHtml}</div></div>
    <p class="muted-note mt">${esc(t('ranking'))}: ${esc(t('best_f1'))} ${esc(best.f1.short)} ${dec(best.f1.f1)} ·
      verdict min_fall_frames=${(lb.verdictConfig && lb.verdictConfig.min_fall_frames) ?? 1}</p>`;

  _monitorStop = startMonitor(root, params);   // live running-tasks panel + condensed leaderboard
}
