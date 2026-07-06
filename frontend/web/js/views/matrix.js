// views/matrix.js — cross-dataset F1 (detector × dataset): normalized heatmap,
// rank badges, mean column, per-dataset leaders, clickable cells.
import { getEvals, leaderboard } from '../store.js';
import { dsLabel, shortName, family, dec, roman } from '../format.js';
import { qs, esc, spinner, empty } from '../components.js';
import { t } from '../i18n.js';
import { href } from '../router.js';
import { leakCategory, CAT } from '../leakage.js';

export async function render(root) {
  root.innerHTML = `<div class="eyebrow"><span class="n">03</span>${esc(t('matrix_h'))}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(t('matrix_h'))}</h1>
    <p class="page-sub">${esc(t('matrix_sub'))}</p>
    <div id="mx">${spinner('…')}</div>`;
  const el = qs('#mx', root);

  let evals;
  try { evals = await getEvals(); } catch (e) { el.innerHTML = empty('error', e.message || e); return; }
  const datasets = [...new Set(evals.filter(e => e.status === 'completed' || e.status === 'partial')
                                    .map(e => e.dataset_name))];
  if (!datasets.length) { el.innerHTML = empty(t('no_data'), t('no_evals_b')); return; }

  const lbs = {};
  await Promise.all(datasets.map(async ds => { lbs[ds] = await leaderboard(ds); }));

  // cell[det][ds] = { f1, rank, evalId }
  const detSet = new Set();
  const cell = {};
  for (const ds of datasets) {
    const rows = lbs[ds].rows.slice().sort((a, b) => b.f1 - a.f1);
    rows.forEach((r, i) => {
      detSet.add(r.name);
      (cell[r.name] = cell[r.name] || {})[ds] = { f1: r.f1, rank: i + 1, evalId: r.evalId };
    });
  }
  // generalisation mean: TRAIN cells (memorisation) are excluded per the thesis
  const meanOf = (n) => {
    const vs = datasets.filter(d => cell[n][d] != null && leakCategory(n, d) !== 'train')
                       .map(d => cell[n][d].f1);
    return vs.length ? vs.reduce((a, b) => a + b) / vs.length : 0;
  };
  const dets = [...detSet].sort((a, b) => meanOf(b) - meanOf(a));

  // normalize colors to the actual F1 range so differences are visible
  const allV = dets.flatMap(n => datasets.map(d => cell[n][d]?.f1).filter(v => v != null));
  const minV = Math.min(...allV), maxV = Math.max(...allV);
  const norm = (v) => maxV > minV ? (v - minV) / (maxV - minV) : 0.5;
  const heat = (v) => v == null ? 'var(--panel-2)' : `rgba(59,130,246,${(0.12 + norm(v) * 0.74).toFixed(3)})`;

  // leaders per dataset (thesis signal) — TRAIN cells can't claim the crown
  const leaders = datasets.map(d => {
    const top = lbs[d].rows.slice()
      .filter(r => leakCategory(r.name, d) !== 'train')
      .sort((a, b) => b.f1 - a.f1)[0];
    return { d, det: top ? shortName(top.name) : '–', f1: top ? top.f1 : null };
  });
  const uniqueLeaders = new Set(leaders.map(l => l.det)).size;

  const head = `<tr><th class="mtx-fam"></th><th class="mtx-name"></th>${datasets.map(d =>
    `<th><a href="${href('/', { ds: d })}">${esc(dsLabel(d))}</a></th>`).join('')}<th title="${esc(t('matrix_mean_excl'))}">⌀ ${esc(t('lab_avgf1'))} *</th></tr>`;

  const rows = dets.map(n => {
    const mean = meanOf(n);
    const cells = datasets.map(d => {
      const c = cell[n][d];
      if (!c) return `<td class="cell empty" title="not evaluated">–</td>`;
      const rk = c.rank <= 3 ? `<span class="sup">${roman(c.rank)}</span>` : '';
      const link = c.evalId ? href('/eval', { id: c.evalId }) : href('/', { ds: d });
      const cat = leakCategory(n, d), cm = CAT[cat];
      const mark = cm.mark ? `<span class="catmark ${cm.cls}">${cm.mark}</span>` : '';
      const leakCls = cat !== 'ood' ? ` leak-${cm.cls}` : '';
      const catTip = cm.mark ? ` · ${t(cm.tip)}` : '';
      const rank1 = c.rank === 1 && cat !== 'train';
      return `<td class="cell${leakCls}" style="background:${heat(c.f1)};${rank1 ? 'outline:2px solid var(--accent);outline-offset:-2px;' : ''}"
        title="${esc(shortName(n))} · ${esc(dsLabel(d))} = F1 ${dec(c.f1)} (rank ${roman(c.rank)})${esc(catTip)}">
        ${mark}<a href="${link}"><span class="val">${dec(c.f1, 2)}</span>${rk}</a></td>`;
    }).join('');
    return `<tr>
      <th class="mtx-fam"><a href="${href('/detectors', { name: n })}"><span class="fam">${family(n)}</span></a></th>
      <th class="mtx-name"><a href="${href('/detectors', { name: n })}">${esc(shortName(n))}</a></th>
      ${cells}
      <td class="cell mean" style="background:${heat(mean)}" title="mean F1 = ${dec(mean)}"><span class="val">${dec(mean, 2)}</span></td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div class="panel" style="overflow:auto"><table class="heat mtx">${head}${rows}</table></div>
    <div class="row mt" style="gap:1.4rem;align-items:center">
      <div class="row" style="gap:.5rem;align-items:center">
        <span class="dim mono" style="font-size:.66rem">F1</span>
        <span class="num">${dec(minV, 2)}</span><span class="colorbar"></span><span class="num">${dec(maxV, 2)}</span>
      </div>
      <span class="dim mono" style="font-size:.66rem">${esc(t('matrix_legend'))}</span>
    </div>
    <div class="row mt leak-legend" style="gap:.7rem;flex-wrap:wrap;align-items:center">
      <span class="catmark train">T</span><span class="dim mono">${esc(t('cat_train'))}</span>
      <span class="catmark eval">E</span><span class="dim mono">${esc(t('cat_eval'))}</span>
      <span class="catmark unknown">?</span><span class="dim mono">${esc(t('cat_unknown'))}</span>
      <span class="dim mono" style="opacity:.7">·&nbsp; ${esc(t('cat_ood'))} ${esc(t('leak_legend_note'))}</span>
    </div>
    <div class="panel section"><div class="panel-h">${esc(t('matrix_leader'))}</div>
      <div class="row" style="gap:.6rem;flex-wrap:wrap">${leaders.map(l =>
        `<span class="badge ${l.det !== '–' ? 'info' : 'muted'}">${esc(dsLabel(l.d))}<span class="hl" style="margin:0 .35rem">${esc(l.det)}</span>${l.f1 != null ? dec(l.f1, 2) : ''}</span>`).join('')}</div>
      <p class="muted-note mt">${esc(uniqueLeaders > 1 ? t('matrix_reshuffle') : t('matrix_same'))}</p>
    </div>`;
}
