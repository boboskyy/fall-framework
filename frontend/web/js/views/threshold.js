// views/threshold.js — verdict-threshold sensitivity (H4). Everything recomputes
// live from per-clip fall_frame_count; no re-evaluation.
import { getEvals, leaderboard } from '../store.js';
import { dsLabel, shortName, family, dec, countsAtThreshold, MAX_THRESHOLD, ALL_DS } from '../format.js';
import { stripedBar, lineChart, histogram, colorFor } from '../charts.js';
import { qs, qsa, esc, spinner, empty } from '../components.js';
import { t } from '../i18n.js';
import { href, go } from '../router.js';

async function dsOptions(selected) {
  const evals = await getEvals();
  const list = [...new Set(evals.filter(e => e.status === 'completed' || e.status === 'partial').map(e => e.dataset_name))];
  const html = `<option value="${ALL_DS}" ${selected === ALL_DS ? 'selected' : ''}>${esc(dsLabel(ALL_DS))}</option>` +
    list.map(d => `<option value="${d}" ${d === selected ? 'selected' : ''}>${esc(dsLabel(d))}</option>`).join('');
  return { list, html };
}

export async function render(root, params) {
  root.innerHTML = `<div class="eyebrow"><span class="n">02</span>${esc(t('th_h'))}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(t('th_h'))}</h1>
    <p class="page-sub">${esc(t('th_sub'))}</p>
    <div id="th">${spinner('…')}</div>`;
  const el = qs('#th', root);

  const { list } = await dsOptions(params.ds);
  if (!list.length) { el.innerHTML = empty(t('no_data'), t('no_evals_b')); return; }
  const ds = (params.ds === ALL_DS || (params.ds && list.includes(params.ds))) ? params.ds : list[0];
  const opt = (await dsOptions(ds)).html;

  const lb = await leaderboard(ds);
  if (!lb.rows.length) { el.innerHTML = empty(t('no_evals_h')); return; }

  // F1 curves per detector across thresholds 1..MAX
  const series = lb.rows.map((r, i) => ({
    name: r.short, color: colorFor(i),
    points: Array.from({ length: MAX_THRESHOLD }, (_, j) => [j + 1, countsAtThreshold(r.perFile, j + 1).f1]),
  }));

  el.innerHTML = `
    <div class="row between mb">
      <div class="select"><select id="ds-sel">${opt}</select></div>
      <a class="btn ghost sm" href="${href('/', { ds })}">← ${esc(t('nav_lab'))}</a>
    </div>
    <div class="panel section">
      <div class="slider-wrap">
        <span class="mono dim">min_fall_frames</span>
        <input type="range" id="thr" min="1" max="${MAX_THRESHOLD}" value="1">
        <span class="slider-val" id="thr-v">1</span>
      </div>
    </div>
    <div class="grid cols-2 section" style="align-items:start">
      <div class="panel"><div class="panel-h">${esc(t('f1_curve'))}</div><div id="curve"></div>
        <div class="legend" id="legend"></div></div>
      <div class="panel"><div class="panel-h">${esc(t('leaderboard_at'))} <span id="lb-k" class="acc">1</span></div>
        <div class="lb" id="lb-th"></div></div>
    </div>
    <div class="panel section">
      <div class="row between">
        <div class="panel-h" style="margin:0">${esc(t('ff_hist'))}</div>
        <div class="select"><select id="hist-det">${lb.rows.map(r => `<option value="${r.name}">${esc(r.short)}</option>`).join('')}</select></div>
      </div>
      <div id="hist" class="mt"></div>
      <div id="hist-tag" class="muted-note mt"></div>
    </div>`;

  qs('#ds-sel', el).addEventListener('change', e => go(href('/threshold', { ds: e.target.value }).slice(1)));

  const drawCurve = (k) => {
    qs('#curve', el).innerHTML = lineChart(series, {
      xDomain: [1, MAX_THRESHOLD], yDomain: [0, 1], xLabel: 'threshold', yLabel: 'F1', marker: k,
    });
    qs('#legend', el).innerHTML = series.map((s, i) =>
      `<span class="it"><span class="sw" style="background:${s.color}"></span>${esc(s.name)}</span>`).join('');
  };

  const drawLb = (k) => {
    const rows = lb.rows.map(r => ({ r, m: countsAtThreshold(r.perFile, k) })).sort((a, b) => b.m.f1 - a.m.f1);
    qs('#lb-k', el).textContent = k;
    qs('#lb-th', el).innerHTML = rows.map((x, i) => `
      <div class="lb-row ${i === 0 ? 'best' : ''}">
        <div class="rank r${i + 1}">${i + 1}</div>
        <div class="lb-name"><span class="fam">${family(x.r.name)}</span><span class="nm">${esc(x.r.short)}</span></div>
        ${stripedBar(x.m.f1, { best: i === 0 })}
        <div class="lb-val">${dec(x.m.f1)}</div>
      </div>`).join('');
  };

  const drawHist = (k) => {
    const det = qs('#hist-det', el).value;
    const row = lb.rows.find(r => r.name === det);
    const bins = new Array(MAX_THRESHOLD + 1).fill(0);
    const vals = [];
    for (const r of row.perFile) {
      const v = Math.min(MAX_THRESHOLD, r.detector_fall_frame_count || 0);
      bins[v]++; vals.push(r.detector_fall_frame_count || 0);
    }
    vals.sort((a, b) => a - b);
    const mid = Math.floor((vals.length - 1) / 2);
    const median = vals.length ? (vals.length % 2 ? vals[mid] : (vals[mid] + vals[mid + 1]) / 2) : 0;
    qs('#hist', el).innerHTML = histogram(bins, {
      labels: bins.map((_, i) => i % 5 === 0 ? (i === MAX_THRESHOLD ? i + '+' : i) : ''),
      hl: (i) => i >= k,
    });
    const kind = median <= 2 ? 'event-type (max 1–2 fall frames → collapses past low thresholds)'
                             : 'sustained (broad fall-frame mass → threshold-stable)';
    qs('#hist-tag', el).innerHTML = `median fall_frames = <span class="hl num">${median}</span> → <span class="acc">${kind}</span>`;
  };

  const redraw = (k) => { drawCurve(k); drawLb(k); drawHist(k); };
  const slider = qs('#thr', el);
  slider.addEventListener('input', () => { const k = +slider.value; qs('#thr-v', el).textContent = k; redraw(k); });
  qs('#hist-det', el).addEventListener('change', () => drawHist(+slider.value));
  redraw(1);
}
