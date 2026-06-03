// views/detectors.js — detector catalogue (research-leaning: family, health,
// aggregate stats). ?name= shows one detector's detail.
import { api } from '../api.js';
import { shortName, family, FAMILY_LABEL, dsLabel, dec, pct, ms } from '../format.js';
import { qs, qsa, esc, spinner, empty, healthBadge, toast } from '../components.js';
import { stripedBar } from '../charts.js';
import { isPreview } from '../config.js';
import { t } from '../i18n.js';
import { href } from '../router.js';

export async function render(root, params) {
  if (params.name) return detail(root, params.name);

  root.innerHTML = `<div class="eyebrow"><span class="n">04</span>${esc(t('detectors_h'))}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(t('detectors_h'))}</h1>
    <p class="page-sub" id="d-sub">6 rodzin algorytmicznych (A–F)</p>
    ${isPreview() ? '' : `<div class="btn-row mb">
      <button class="btn ghost sm" id="rescan">${esc(t('rescan'))}</button>
      <input class="ipt" id="tpl-name" placeholder="new_detector_name" style="max-width:210px">
      <button class="btn sm" id="get-tpl">${esc(t('template'))}</button>
    </div>`}
    <div id="d-body">${spinner('…')}</div>`;
  const body = qs('#d-body', root);

  if (!isPreview()) {
    qs('#rescan', root).addEventListener('click', async (e) => {
      e.target.disabled = true; e.target.textContent = '…';
      try { await api.rescanDetectors(); toast('detectors rescanned', 'ok'); render(root, params); }
      catch (err) { toast(err.message || err, 'err'); e.target.disabled = false; e.target.textContent = t('rescan'); }
    });
    qs('#get-tpl', root).addEventListener('click', () => {
      const name = qs('#tpl-name', root).value.trim();
      if (!/^[a-z0-9_]+$/.test(name)) { toast('name: lowercase letters, digits, underscore', 'err'); return; }
      window.open(api.templateUrl(name), '_blank');
    });
  }

  let dets, summary = [];
  try {
    dets = (await api.detectors()).detectors || [];
    summary = await api.detectorsSummary().catch(() => []);
  } catch (e) { body.innerHTML = empty('error', e.message || e); return; }
  const subEl = qs('#d-sub', root);
  if (subEl) subEl.textContent = `${dets.length} ${t('detectors')} · 6 rodzin algorytmicznych (A–F)`;
  const sumBy = Object.fromEntries(summary.map(s => [s.detector_name, s]));

  // group by family
  const fams = {};
  for (const d of dets) (fams[family(d.name)] = fams[family(d.name)] || []).push(d);

  body.innerHTML = Object.keys(fams).sort().map(f => `
    <div class="section">
      <h2 class="sec-h">${f} — ${esc(FAMILY_LABEL[f] || '')}<span class="rule"></span>
        <span class="meta">${fams[f].length}</span></h2>
      <div class="grid auto cards">
        ${fams[f].map(d => {
          const s = sumBy[d.name] || {};
          const f1 = s.overall_f1, acc = s.overall_accuracy;
          return `<a class="panel" href="${href('/detectors', { name: d.name })}" style="text-decoration:none">
            <div class="row between">
              <strong class="mono hl">${esc(shortName(d.name))}</strong>
              ${healthBadge(d.container_status)}
            </div>
            <p class="desc clamp3" style="margin:.55rem 0 0">${esc(d.description || d.category || '')}</p>
            <div class="row" style="gap:1.4rem;margin-top:auto;padding-top:.85rem">
              <div><div class="k mono" style="font-size:.6rem;color:var(--muted)">F1 (overall)</div>
                <div class="num hl">${f1 != null ? dec(f1) : '–'}</div></div>
              <div><div class="k mono" style="font-size:.6rem;color:var(--muted)">EVALS</div>
                <div class="num">${s.total_evaluations ?? 0}</div></div>
              <div><div class="k mono" style="font-size:.6rem;color:var(--muted)">${d.requires_gpu ? 'GPU' : 'CPU'}</div>
                <div class="num dim">:${d.port}</div></div>
            </div>
          </a>`;
        }).join('')}
      </div>
    </div>`).join('');
}

async function detail(root, name) {
  root.innerHTML = `<div class="eyebrow"><span class="n">04</span>${esc(family(name))} — ${esc(FAMILY_LABEL[family(name)] || '')}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(shortName(name))}</h1>
    <div class="btn-row mb"><a class="btn ghost sm" href="${href('/detectors')}">← ${esc(t('detectors_h'))}</a></div>
    <div id="dd">${spinner('…')}</div>`;
  const el = qs('#dd', root);
  let stats, info;
  try {
    info = await api.detector(name);
    stats = await api.detectorStats(name).catch(() => null);
  } catch (e) { el.innerHTML = empty('error', e.message || e); return; }

  const inf = info.detector || {};
  // /detectors/<name>/stats returns a nested envelope: { evaluation_stats:{...} }
  const ev = (stats && stats.evaluation_stats) || {};
  const safeHref = (u) => (u && /^https?:\/\//i.test(u)) ? u : null;
  const src = safeHref(inf.github_url);

  // aggregate confusion matrix (uses the .cm theme block)
  let cm = '';
  if (ev.total_files_evaluated) {
    cm = `<div class="section"><h2 class="sec-h">confusion (all evaluations)<span class="rule"></span>
        ${ev.tendency ? `<span class="meta">${esc(ev.tendency.replace(/_/g, ' '))}</span>` : ''}</h2>
      <div class="panel"><div class="cm" style="max-width:380px">
        <div class="cell hd"></div><div class="cell hd">pred FALL</div><div class="cell hd">pred ADL</div>
        <div class="cell hd">GT FALL</div><div class="cell tp"><div class="v">${ev.tp ?? 0}</div><div class="lab">TP</div></div><div class="cell fn"><div class="v">${ev.fn ?? 0}</div><div class="lab">FN</div></div>
        <div class="cell hd">GT ADL</div><div class="cell fp"><div class="v">${ev.fp ?? 0}</div><div class="lab">FP</div></div><div class="cell tn"><div class="v">${ev.tn ?? 0}</div><div class="lab">TN</div></div>
      </div></div></div>`;
  }

  let perDs = '';
  const pd = Array.isArray(ev.per_dataset) ? ev.per_dataset : [];
  if (pd.length) {
    perDs = `<div class="section"><h2 class="sec-h">per-dataset<span class="rule"></span></h2>
      <div class="panel"><div class="lb">${pd.map(v => {
        const acc = v.accuracy != null ? v.accuracy
          : ((v.tp + v.tn + v.fp + v.fn) ? (v.tp + v.tn) / (v.tp + v.tn + v.fp + v.fn) : 0);
        return `<div class="lb-row"><div></div>
          <div class="lb-name"><span class="nm">${esc(dsLabel(v.dataset_name))}</span>
            <span class="dim mono" style="margin-left:.5rem">${v.total_files ?? 0} clips</span></div>
          ${stripedBar(acc)}<div class="lb-val">${dec(acc)}</div></div>`;
      }).join('')}</div></div></div>`;
  }

  el.innerHTML = `
    <div class="grid cols-4 section">
      <div class="stat"><div class="k">health</div><div class="v small">${healthBadge(inf.container_status)}</div></div>
      <div class="stat"><div class="k">evaluations</div><div class="v">${ev.total_evaluations ?? 0}</div></div>
      <div class="stat"><div class="k">files evaluated</div><div class="v">${ev.total_files_evaluated ?? 0}</div></div>
      <div class="stat"><div class="k">avg time</div><div class="v small">${ev.avg_processing_time_ms != null ? ms(ev.avg_processing_time_ms) : '–'}</div></div>
    </div>
    <div class="panel section">
      <p class="desc">${esc(inf.description || '')}</p>
      <div class="metabar">
        <span class="badge info"><span class="fam" style="width:1rem;height:1rem;font-size:.58rem;border:none">${family(name)}</span>${esc(FAMILY_LABEL[family(name)] || '')}</span>
        ${inf.category ? `<span class="badge muted">${esc(inf.category)}</span>` : ''}
        <span class="badge muted">${esc((inf.supported_input_types || []).join(', ') || 'video')}</span>
        <span class="badge ${inf.requires_gpu ? 'info' : 'muted'}">${inf.requires_gpu ? 'GPU' : 'CPU'}${inf.device ? ' · ' + esc(inf.device) : ''}</span>
        <span class="badge muted">:${inf.port}</span>
        ${src ? `<a class="badge info" href="${esc(src)}" target="_blank" rel="noopener">source ↗</a>` : ''}
      </div>
    </div>
    ${cm}
    ${perDs}`;
}
