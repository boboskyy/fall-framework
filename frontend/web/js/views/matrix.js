// views/matrix.js — cross-dataset F1 (detector × dataset) with rank badges.
import { getEvals, leaderboard } from '../store.js';
import { dsLabel, shortName, family, dec } from '../format.js';
import { qs, esc, spinner, empty } from '../components.js';
import { t } from '../i18n.js';
import { href } from '../router.js';

const CIRC = ['', '①', '②', '③'];
const f1Color = (v) => v == null ? 'var(--panel)' : `rgba(255,255,255,${(0.05 + v * 0.55).toFixed(3)})`;

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

  // detector union + per-column ranks
  const detSet = new Set();
  const cell = {}; // det -> ds -> {f1, rank}
  for (const ds of datasets) {
    const rows = lbs[ds].rows.slice().sort((a, b) => b.f1 - a.f1);
    rows.forEach((r, i) => {
      detSet.add(r.name);
      cell[r.name] = cell[r.name] || {};
      cell[r.name][ds] = { f1: r.f1, rank: i + 1 };
    });
  }
  // order detectors by mean F1 desc
  const dets = [...detSet].sort((a, b) => {
    const m = (n) => { const vs = datasets.map(d => cell[n][d]?.f1).filter(v => v != null); return vs.length ? vs.reduce((x, y) => x + y) / vs.length : 0; };
    return m(b) - m(a);
  });

  const head = `<tr><th></th>${datasets.map(d => `<th>${esc(dsLabel(d))}</th>`).join('')}</tr>`;
  const rows = dets.map(n => `<tr>
      <th style="text-align:right"><span class="fam" style="margin-right:.4rem">${family(n)}</span>${esc(shortName(n))}</th>
      ${datasets.map(d => {
        const c = cell[n][d];
        if (!c) return `<td class="cell" style="background:var(--panel-2);color:var(--muted)">·</td>`;
        const rk = c.rank <= 3 ? `<sup style="color:var(--accent)">${CIRC[c.rank]}</sup>` : '';
        const isTop = c.rank === 1;
        return `<td class="cell" title="${esc(shortName(n))} · ${esc(dsLabel(d))} = F1 ${dec(c.f1)}"
          style="background:${f1Color(c.f1)};${isTop ? 'outline:1px solid var(--accent);' : ''}">${dec(c.f1, 2)}${rk}</td>`;
      }).join('')}
    </tr>`).join('');

  el.innerHTML = `<div class="panel" style="overflow:auto">
      <table class="heat">${head}${rows}</table>
    </div>
    <p class="muted-note mt">darker cell = higher F1 · ①②③ = rank within dataset · → leader changes per dataset = no universally best detector.</p>`;
}
