// views/diversity.js — shared errors & diversity (Badanie B): κ matrix on error
// vectors, double-fault explorer, recall–FPR scatter (H3). Computed client-side
// from per-clip verdicts.
import { getEvals, leaderboard, kappa } from '../store.js';
import { dsLabel, shortName, family, dec } from '../format.js';
import { kappaColor, scatter } from '../charts.js';
import { qs, esc, spinner, empty } from '../components.js';
import { t } from '../i18n.js';
import { href, go } from '../router.js';

export async function render(root, params) {
  root.innerHTML = `<div class="eyebrow"><span class="n">02</span>${esc(t('div_h'))}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(t('div_h'))}</h1>
    <p class="page-sub">${esc(t('div_sub'))}</p>
    <div id="dv">${spinner('…')}</div>`;
  const el = qs('#dv', root);

  const evals = await getEvals().catch(() => []);
  const list = [...new Set(evals.filter(e => e.status === 'completed' || e.status === 'partial').map(e => e.dataset_name))];
  if (!list.length) { el.innerHTML = empty(t('no_data'), t('no_evals_b')); return; }
  const ds = (params.ds && list.includes(params.ds)) ? params.ds : list[0];

  const lb = await leaderboard(ds);
  const rows = lb.rows;
  if (rows.length < 2) { el.innerHTML = empty('need ≥2 detectors', 'Evaluate more detectors on this dataset.'); return; }

  // pairwise κ + double-fault (recomputed at the eval's own verdict threshold)
  const K0 = (lb.verdictConfig && lb.verdictConfig.min_fall_frames) || 1;
  const N = rows.length;
  const K = Array.from({ length: N }, () => new Array(N).fill(null));
  const pairs = [];
  for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
    if (i === j) continue;
    const r = kappa(rows[i], rows[j], K0);
    K[i][j] = r.k;
    if (i < j) pairs.push({ a: rows[i], b: rows[j], k: r.k, df: r.df, n: r.n });
  }

  const optHtml = list.map(d => `<option value="${d}" ${d === ds ? 'selected' : ''}>${esc(dsLabel(d))}</option>`).join('');

  // κ heatmap
  const head = `<tr><th></th>${rows.map(r => `<th class="rot">${esc(r.short)}</th>`).join('')}</tr>`;
  const body = rows.map((r, i) => `<tr>
      <th style="text-align:right"><span class="fam" style="margin-right:.35rem">${family(r.name)}</span>${esc(r.short)}</th>
      ${rows.map((c, j) => {
        if (i === j) return `<td class="cell diag">—</td>`;
        const v = K[i][j];
        return `<td class="cell" style="background:${kappaColor(v)}" title="${esc(r.short)} × ${esc(c.short)} = κ ${dec(v, 2)}">${dec(v, 2)}</td>`;
      }).join('')}
    </tr>`).join('');

  // double-fault ranking (low df = complementary = good ensemble candidate)
  pairs.sort((a, b) => a.df - b.df);
  const dfRows = pairs.slice(0, 14).map(p => {
    const complementary = p.df < 0.1 && (p.k == null || p.k < 0.3);
    return `<tr>
      <td class="mono">${esc(p.a.short)} <span class="dim">×</span> ${esc(p.b.short)}</td>
      <td class="num hl">${dec(p.df, 3)}</td>
      <td class="num">${dec(p.k, 2)}</td>
      <td>${complementary ? '<span class="badge ok"><span class="dotled"></span>complementary</span>'
                          : (p.k != null && p.k > 0.6 ? '<span class="badge bad"><span class="dotled"></span>shared bias</span>' : '')}</td>
    </tr>`;
  }).join('');

  // recall–FPR scatter (H3)
  const minFpr = Math.min(...rows.map(r => r.fpr));
  const pts = rows.map(r => ({
    x: r.fpr, y: r.recall, label: r.short,
    best: r.fpr === minFpr, bad: r.fpr > 0.6,
  }));

  el.innerHTML = `
    <div class="row between mb">
      <div class="select"><select id="ds-sel">${optHtml}</select></div>
      <a class="btn ghost sm" href="${href('/', { ds })}">← ${esc(t('nav_lab'))}</a>
    </div>
    <div class="grid cols-2 section" style="align-items:start">
      <div class="panel"><div class="panel-h">${esc(t('kappa_matrix'))}</div>
        <div style="overflow:auto"><table class="heat">${head}${body}</table></div>
        <p class="muted-note mt">white = positive κ (errors co-occur) · blue = negative κ (complementary) · 0 = independent.</p>
      </div>
      <div class="panel"><div class="panel-h">recall vs FPR — H3</div>
        ${scatter(pts, { xLabel: 'FPR', yLabel: 'recall' })}
        <p class="muted-note mt">top-right corner = high recall &amp; high FPR ("criers"). Useless detectors fail on FPR, not recall.</p>
      </div>
    </div>
    <div class="panel section"><div class="panel-h">${esc(t('double_fault'))}</div>
      <div class="tbl-wrap"><table class="tbl">
        <thead><tr><th>pair</th><th class="num">double-fault</th><th class="num">κ</th><th></th></tr></thead>
        <tbody>${dfRows}</tbody></table></div>
      <p class="muted-note mt">low double-fault + low κ = genuinely complementary → ensemble candidate.</p>
    </div>`;

  qs('#ds-sel', el).addEventListener('change', e => go(href('/diversity', { ds: e.target.value }).slice(1)));
}
