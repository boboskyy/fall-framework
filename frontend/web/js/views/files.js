// views/files.js — per-clip results: agreement strip (hardest clips first),
// filterable/sortable long-format table, merged CSV export.
import { getEvals, leaderboard, perFileMatrix } from '../store.js';
import { dsLabel, shortName, family, dec, pct } from '../format.js';
import { qs, qsa, esc, spinner, empty, download } from '../components.js';
import { t } from '../i18n.js';
import { href, go } from '../router.js';

export async function render(root, params) {
  root.innerHTML = `<div class="eyebrow"><span class="n">02</span>${esc(t('files_h'))}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(t('files_h'))}</h1>
    <p class="page-sub">${esc(t('files_sub'))}</p>
    <div id="fl">${spinner('…')}</div>`;
  const el = qs('#fl', root);

  const evals = await getEvals().catch(() => []);
  const list = [...new Set(evals.filter(e => e.status === 'completed' || e.status === 'partial').map(e => e.dataset_name))];
  if (!list.length) { el.innerHTML = empty(t('no_data'), t('no_evals_b')); return; }
  const ds = (params.ds && list.includes(params.ds)) ? params.ds : list[0];
  const focusDet = params.det || null;

  const lb = await leaderboard(ds);
  if (!lb.rows.length) { el.innerHTML = empty(t('no_evals_h')); return; }
  const mat = perFileMatrix(lb.rows);

  // clip difficulty = # detectors wrong
  const difficulty = (clip) => Object.values(clip.byDet).filter(r => r.classification === 'FP' || r.classification === 'FN').length;
  const clips = mat.clips.slice().sort((a, b) => difficulty(b) - difficulty(a));

  const optHtml = list.map(d => `<option value="${d}" ${d === ds ? 'selected' : ''}>${esc(dsLabel(d))}</option>`).join('');

  // agreement strip: one row per detector, cells = clips (hardest first, capped)
  const STRIP_MAX = 160;
  const clipsShown = clips.slice(0, STRIP_MAX);
  const stripRows = lb.rows.map(row => {
    const cells = clipsShown.map(c => {
      const r = c.byDet[row.name];
      if (!r || r.classification == null) return `<div class="c na" title="${esc(c.filename)}"></div>`;
      const wrong = r.classification === 'FP' || r.classification === 'FN';
      return `<div class="c ${wrong ? 'wrong' : 'correct'}" title="${esc(c.filename)} · ${esc(r.classification)}"></div>`;
    }).join('');
    return `<div class="strip-row ${focusDet === row.name ? 'best' : ''}">
      <div class="lab" title="${esc(row.name)}"><span class="fam" style="margin-right:.3rem">${family(row.name)}</span>${esc(row.short)}</div>
      <div class="strip" style="grid-template-columns:repeat(${clipsShown.length},minmax(3px,1fr))">${cells}</div>
    </div>`;
  }).join('');
  const stripNote = clips.length > STRIP_MAX
    ? `<span class="dim">— showing ${STRIP_MAX} hardest of ${clips.length}</span>` : '';

  const verdictStr = (v) => (v === 'FALL' || v === true) ? 'FALL' : (v === 'ADL' || v === false) ? 'ADL' : '–';

  // long-format rows for table
  const flat = [];
  for (const row of lb.rows) for (const r of row.perFile) {
    flat.push({
      filename: r.filename, gt: r.ground_truth_label, detector: row.short, detName: row.name,
      verdict: verdictStr(r.detector_verdict),
      classification: r.classification, fall_frames: r.detector_fall_frame_count,
      total_frames: r.detector_total_frames, confidence: r.detector_confidence, time: r.processing_time_ms,
    });
  }

  el.innerHTML = `
    <div class="row between mb">
      <div class="select"><select id="ds-sel">${optHtml}</select></div>
      <div class="btn-row">
        <select id="filter">
          <option value="all">${esc(t('all'))}</option>
          <option value="err">${esc(t('errors_only'))}</option>
          <option value="FP">FP</option><option value="FN">FN</option>
          <option value="TP">TP</option><option value="TN">TN</option>
        </select>
        ${focusDet ? `<select id="detf"><option value="">all detectors</option></select>` : ''}
        <button class="btn sm" id="csv">${esc(t('export_csv'))}</button>
      </div>
    </div>
    <div class="panel section"><div class="panel-h">${esc(t('agreement_strip'))} <span class="dim">— hardest clips left</span> ${stripNote}</div>
      <div style="overflow-x:auto">${stripRows}</div>
      <div class="legend mt">
        <span class="it"><span class="sw" style="background:var(--ok-dim);border:1px solid rgba(152,195,121,.4)"></span>correct</span>
        <span class="it"><span class="sw" style="background:var(--err-dim);border:1px solid rgba(224,108,117,.5)"></span>wrong</span>
      </div>
    </div>
    <div class="panel"><div class="panel-h">per-clip × detector <span class="dim" id="cnt"></span></div>
      <div class="tbl-wrap"><table class="tbl" id="tbl">
        <thead><tr>
          <th data-k="filename">clip</th><th data-k="gt">GT</th><th data-k="detector">detector</th>
          <th data-k="verdict">verdict</th><th data-k="classification">cls</th>
          <th class="num" data-k="fall_frames">fall_frames</th><th class="num" data-k="total_frames">frames</th>
          <th class="num" data-k="confidence">conf</th><th class="num" data-k="time">ms</th>
        </tr></thead><tbody id="tb"></tbody></table></div>
    </div>`;

  qs('#ds-sel', el).addEventListener('change', e => go(href('/files', { ds: e.target.value }).slice(1)));

  let sortK = 'filename', sortDir = 1, filter = 'all', detFilter = focusDet || '';

  function view() {
    let data = flat.filter(r => {
      if (detFilter && r.detName !== detFilter) return false;
      if (filter === 'all') return true;
      if (filter === 'err') return r.classification === 'FP' || r.classification === 'FN';
      return r.classification === filter;
    });
    data.sort((a, b) => {
      const x = a[sortK], y = b[sortK];
      if (typeof x === 'number') return (x - y) * sortDir;
      return String(x).localeCompare(String(y)) * sortDir;
    });
    qs('#tb', el).innerHTML = data.slice(0, 1500).map(r => `<tr>
      <td class="mono">${esc(r.filename)}</td>
      <td><span class="badge ${r.gt === 'FALL' ? 'warn' : 'muted'}">${esc(r.gt)}</span></td>
      <td class="mono">${esc(r.detector)}</td>
      <td class="mono ${r.verdict === 'FALL' ? 'acc' : 'dim'}">${esc(r.verdict)}</td>
      <td>${r.classification ? `<span class="cls ${r.classification}">${r.classification}</span>` : '<span class="cls dim">·</span>'}</td>
      <td class="num">${r.fall_frames}</td><td class="num dim">${r.total_frames}</td>
      <td class="num">${r.confidence != null ? dec(r.confidence, 2) : '–'}</td>
      <td class="num dim">${r.time}</td>
    </tr>`).join('');
    qs('#cnt', el).textContent = `· ${data.length} rows`;
  }

  qsa('#tbl th', el).forEach(th => th.addEventListener('click', () => {
    const k = th.dataset.k; if (!k) return;
    if (sortK === k) sortDir *= -1; else { sortK = k; sortDir = 1; }
    view();
  }));
  qs('#filter', el).addEventListener('change', e => { filter = e.target.value; view(); });
  const detfEl = qs('#detf', el);
  if (detfEl) {
    detfEl.innerHTML = `<option value="">all detectors</option>` +
      lb.rows.map(r => `<option value="${r.name}" ${r.name === detFilter ? 'selected' : ''}>${esc(r.short)}</option>`).join('');
    detfEl.addEventListener('change', e => { detFilter = e.target.value; view(); });
  }
  qs('#csv', el).addEventListener('click', () => {
    const cell = (v) => {
      if (v === null || v === undefined) return '';
      const s = String(v);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const header = ['filename', 'ground_truth', 'detector', 'verdict', 'classification', 'fall_frames', 'total_frames', 'confidence', 'processing_time_ms'];
    const lines = [header.join(',')];
    for (const r of flat) lines.push([r.filename, r.gt, r.detName, r.verdict, r.classification, r.fall_frames, r.total_frames, r.confidence, r.time].map(cell).join(','));
    download(`fallfw_${ds}_perclip.csv`, lines.join('\n'));
  });

  view();
}
