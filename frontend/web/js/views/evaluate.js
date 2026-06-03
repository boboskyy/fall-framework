// views/evaluate.js — launch an evaluation and watch it live (SSE → polling
// fallback). Also lists recent evaluations.
import { api } from '../api.js';
import { getDatasets, getEvals, invalidate } from '../store.js';
import { dsLabel, shortName, family, dec, ago } from '../format.js';
import { stripedBar } from '../charts.js';
import { qs, qsa, esc, spinner, empty, toast, healthBadge } from '../components.js';
import { watchEvaluation } from '../live.js';
import { t } from '../i18n.js';
import { href, go } from '../router.js';

let activeStop = null;

export async function render(root, params) {
  if (activeStop) { activeStop(); activeStop = null; }
  root.innerHTML = `<div class="eyebrow"><span class="n">06</span>${esc(t('eval_h'))}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(t('eval_h'))}</h1>
    <p class="page-sub">${esc(t('eval_sub'))}</p>
    <div id="ev">${spinner('…')}</div>`;
  const el = qs('#ev', root);

  let datasets, dets;
  try {
    datasets = await getDatasets();
    dets = (await api.detectors()).detectors || [];
  } catch (e) { el.innerHTML = empty('error', e.message || e); return; }

  const dsOpt = datasets.map(d => `<option value="${d.name}">${esc(dsLabel(d.name))}</option>`).join('');
  const chips = dets.sort((a, b) => family(a.name).localeCompare(family(b.name))).map(d =>
    `<button class="chip" data-det="${esc(d.name)}" ${d.container_status !== 'healthy' ? 'data-unhealthy="1"' : ''}>
      <span class="fam">${family(d.name)}</span>${esc(shortName(d.name))}
      ${d.container_status !== 'healthy' ? `<span class="badge bad" style="padding:.05rem .25rem">${esc(d.container_status)}</span>` : ''}
    </button>`).join('');

  el.innerHTML = `
    <div class="panel section">
      <div class="row mb">
        <span class="mono dim">${esc(t('dataset'))}</span>
        <div class="select"><select id="ds">${dsOpt}</select></div>
        <span class="spread"></span>
        <button class="btn ghost sm" id="all">${esc(t('select_all'))}</button>
        <button class="btn ghost sm" id="clear">${esc(t('clear'))}</button>
      </div>
      <div class="panel-h">${esc(t('select_detectors'))}</div>
      <div class="chips" id="chips">${chips}</div>
      <div class="btn-row mt">
        <button class="btn" id="start">▶ ${esc(t('start'))}</button>
        <span class="mono dim" id="sel-count">0</span>
      </div>
    </div>
    <div id="live"></div>
    <div class="section"><h2 class="sec-h">${esc(t('nav_evaluate'))} — history<span class="rule"></span></h2><div id="hist">${spinner('…')}</div></div>`;

  const sel = new Set();
  const refreshCount = () => { qs('#sel-count', el).textContent = `${sel.size} selected`; };
  qsa('#chips .chip', el).forEach(c => c.addEventListener('click', () => {
    const n = c.dataset.det;
    if (sel.has(n)) { sel.delete(n); c.classList.remove('selected'); }
    else { sel.add(n); c.classList.add('selected'); }
    refreshCount();
  }));
  qs('#all', el).addEventListener('click', () => { qsa('#chips .chip', el).forEach(c => { sel.add(c.dataset.det); c.classList.add('selected'); }); refreshCount(); });
  qs('#clear', el).addEventListener('click', () => { sel.clear(); qsa('#chips .chip', el).forEach(c => c.classList.remove('selected')); refreshCount(); });

  qs('#start', el).addEventListener('click', async () => {
    if (!sel.size) { toast('Select at least one detector', 'err'); return; }
    const dataset = qs('#ds', el).value;
    const btn = qs('#start', el); btn.disabled = true; btn.textContent = '…';
    try {
      const r = await api.startEval({
        dataset, detectors: [...sel], selected_files: null,
        verdict_config: { min_fall_frames: 1, min_fall_percentage: 0.0 }, sync: false,
      });
      invalidate();
      toast('Evaluation started', 'ok');
      startCockpit(r.eval_id || r.evaluation_id || r.id, dataset, [...sel]);
    } catch (e) { toast(e.message || e, 'err'); }
    btn.disabled = false; btn.textContent = '▶ ' + t('start');
  });

  function startCockpit(evalId, dataset, detectorNames) {
    const live = qs('#live', el);
    const draw = (s) => {
      const pctv = s.progress_pct ?? (s.total_tasks ? (s.completed_tasks / s.total_tasks * 100) : 0);
      const perDet = s.per_detector || null;
      const rowsHtml = detectorNames.map(n => {
        const pd = perDet && perDet[n];
        let st = 'running', extra = '';
        if (pd) { st = pd.status || (pd.completed >= pd.total ? 'done' : 'running'); extra = `${pd.completed}/${pd.total}`; }
        else if (s.status === 'completed') { st = 'done'; }
        return `<div class="lr ${st}"><span class="nm"><span class="fam" style="margin-right:.3rem">${family(n)}</span>${esc(shortName(n))}</span>
          <span class="dim mono">${esc(extra || st)}</span><span></span></div>`;
      }).join('');
      live.innerHTML = `<div class="live-banner section">
        <div class="live-head">${['completed', 'failed', 'cancelled', 'partial'].includes(s.status) ? '' : '<span class="pulse"></span>'}
          <span>${s.status === 'completed' ? '✓ ' : ''}${esc(t('eval_h'))} — ${esc(dsLabel(dataset))} · ${detectorNames.length} ${esc(t('detectors'))}</span>
          <span class="spread"></span>
          <span class="mono acc">${dec(pctv, 0)}%</span>
          <span class="mono dim">${s.completed_tasks ?? 0}/${s.total_tasks ?? '?'}</span>
        </div>
        ${stripedBar(pctv / 100, { best: s.status === 'completed' })}
        <div class="live-rows">${rowsHtml}</div>
        <div class="btn-row">
          ${['completed', 'partial'].includes(s.status) ? `<a class="btn sm" href="${href('/', { ds: dataset })}">${esc(t('view'))} ${esc(t('ranking'))} →</a>` : ''}
          ${['pending', 'running'].includes(s.status) ? `<button class="btn sm danger" id="cancel">${esc(t('cancel'))}</button>` : ''}
        </div>
      </div>`;
      const c = qs('#cancel', live);
      if (c) c.addEventListener('click', async () => { try { await api.cancelEval(evalId); toast('cancel requested', 'info'); } catch (e) { toast(e.message, 'err'); } });
    };
    draw({ status: 'pending', completed_tasks: 0, total_tasks: detectorNames.length });
    activeStop = watchEvaluation(evalId, {
      onUpdate: draw,
      onDone: (s) => { draw(s); invalidate(); loadHistory(); },
    });
  }

  async function loadHistory() {
    const h = qs('#hist', el);
    try {
      const evals = (await getEvals(true)).slice().reverse();
      h.innerHTML = `<div class="panel"><div class="lb">` + evals.slice(0, 12).map(e => {
        const cls = e.status === 'completed' ? 'ok' : e.status === 'failed' ? 'bad' : e.status === 'partial' ? 'warn' : 'muted';
        return `<a class="lb-row" href="${href('/', { ds: e.dataset_name })}">
          <div></div>
          <div class="lb-name"><span class="nm">${esc(dsLabel(e.dataset_name))}</span>
            <span class="dim mono" style="margin-left:.5rem">${e.detector_names.map(shortName).join(', ')}</span></div>
          <div><span class="badge ${cls}"><span class="dotled"></span>${esc(e.status)}</span></div>
          <div class="lb-val dim">${e.completed_tasks}/${e.total_tasks} · ${ago(e.created_at)}</div>
        </a>`;
      }).join('') + `</div></div>`;
    } catch (e) { h.innerHTML = empty('error', e.message || e); }
  }
  loadHistory();
}
