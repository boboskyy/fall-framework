// views/datasets.js — dataset cards + detail. ?name= shows file breakdown.
import { api } from '../api.js';
import { getDatasets, getEvals, getResults } from '../store.js';
import { dsLabel, dec } from '../format.js';
import { qs, qsa, esc, spinner, empty, toast } from '../components.js';
import { stripedBar } from '../charts.js';
import { isPreview } from '../config.js';
import { t } from '../i18n.js';
import { href } from '../router.js';

export async function render(root, params) {
  if (params.name) return detail(root, params.name);

  root.innerHTML = `<div class="eyebrow"><span class="n">05</span>${esc(t('datasets_h'))}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(t('datasets_h'))}</h1>
    ${isPreview() ? '' : `<div class="btn-row mb">
      <button class="btn sm" id="add-ds">+ ${esc(t('add_dataset'))}</button>
      <button class="btn ghost sm" id="refresh-reg">${esc(t('refresh_registry'))}</button>
    </div>
    <div id="add-panel" class="panel section" style="display:none">
      <div class="panel-h">${esc(t('add_dataset'))}</div>
      <div class="row">
        <input class="ipt" id="ds-name" placeholder="name (optional)">
        <input type="file" id="ds-file" accept=".zip">
        <button class="btn sm" id="do-upload">${esc(t('upload_zip'))}</button>
      </div>
      <div class="muted-note mt">.zip z podfolderami <span class="mono">fall/</span> i <span class="mono">adl/</span> (lub manifestem datasetu).</div>
    </div>`}
    <div id="ds-body">${spinner('…')}</div>`;
  const body = qs('#ds-body', root);

  if (!isPreview()) {
    qs('#add-ds', root).addEventListener('click', () => {
      const p = qs('#add-panel', root);
      p.style.display = p.style.display === 'none' ? 'block' : 'none';
    });
    qs('#refresh-reg', root).addEventListener('click', async (e) => {
      e.target.disabled = true;
      try { await api.refreshRegistry(); await getDatasets(true); toast('registry refreshed', 'ok'); render(root, params); }
      catch (err) { toast(err.message || err, 'err'); e.target.disabled = false; }
    });
    qs('#do-upload', root).addEventListener('click', async () => {
      const f = qs('#ds-file', root).files[0];
      if (!f) { toast('Choose a .zip file', 'err'); return; }
      const btn = qs('#do-upload', root); btn.disabled = true; btn.textContent = '…';
      try {
        await api.uploadDataset(f, qs('#ds-name', root).value.trim() || undefined);
        await getDatasets(true);
        toast('dataset uploaded', 'ok');
        render(root, params);
      } catch (err) { toast(err.message || err, 'err'); btn.disabled = false; btn.textContent = t('upload_zip'); }
    });
  }
  let ds, evals;
  try { ds = await getDatasets(); evals = await getEvals(); }
  catch (e) { body.innerHTML = empty('error', e.message || e); return; }

  const evalCount = {};
  evals.forEach(e => { evalCount[e.dataset_name] = (evalCount[e.dataset_name] || 0) + 1; });

  // The /datasets list endpoint returns empty statistics — derive clips + fall/adl
  // from one completed evaluation per dataset (ground truth is in per_file_results).
  const pick = {};   // biggest (most clips) completed eval per dataset — avoids tiny reruns
  for (const e of evals) {
    if (e.status !== 'completed' && e.status !== 'partial') continue;
    if (!pick[e.dataset_name] || e.completed_tasks > pick[e.dataset_name].completed_tasks) pick[e.dataset_name] = e;
  }
  const derived = {};
  await Promise.all(Object.values(pick).map(async (e) => {
    try {
      const sm = ((await getResults(e.eval_id)).detector_summaries || [])[0];
      const pf = sm && sm.per_file_results;
      if (pf) derived[e.dataset_name] = {
        total: sm.total_files,
        fall: pf.filter(r => r.ground_truth_fall === true).length,
        adl: pf.filter(r => r.ground_truth_fall === false).length,
      };
    } catch {}
  }));

  body.innerHTML = `<div class="grid auto">` + ds.map(d => {
    const st = d.statistics || {};
    const dv = derived[d.name] || {};
    const total = dv.total ?? st.total_files ?? 0;
    const fall = dv.fall ?? st.total_fall ?? 0, adl = dv.adl ?? st.total_adl ?? 0;
    const balance = total ? fall / total : 0;
    const skew = total && (fall / total < 0.2 || adl / total < 0.2);
    return `<a class="panel" href="${href('/datasets', { name: d.name })}" style="text-decoration:none">
      <div class="row between">
        <strong class="mono hl">${esc(dsLabel(d.name))}</strong>
        <span class="badge muted">${evalCount[d.name] || 0} evals</span>
      </div>
      <div class="muted-note" style="margin:.5rem 0">${esc(d.description || d.input_type || '')}</div>
      <div class="row" style="gap:1.4rem">
        <div><div class="k mono" style="font-size:.6rem;color:var(--muted)">CLIPS</div><div class="num hl">${total || '–'}</div></div>
        <div><div class="k mono" style="font-size:.6rem;color:var(--muted)">FALL / ADL</div><div class="num">${fall} / ${adl}</div></div>
      </div>
      <div class="mt">${stripedBar(balance, { cls: balance >= 0.5 ? '' : 'blue' })}</div>
      ${skew ? `<div class="badge warn mt" style="margin-top:.5rem"><span class="dotled"></span>skewed → FPR less reliable</div>` : ''}
    </a>`;
  }).join('') + `</div>`;
}

async function detail(root, name) {
  root.innerHTML = `<div class="eyebrow"><span class="n">05</span>${esc(t('datasets_h'))}</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(dsLabel(name))}</h1>
    <div class="btn-row mb">
      <a class="btn ghost sm" href="${href('/datasets')}">← ${esc(t('datasets_h'))}</a>
      <a class="btn sm" href="${href('/', { ds: name })}">${esc(t('nav_lab'))} →</a></div>
    <div id="dsd">${spinner('…')}</div>`;
  const el = qs('#dsd', root);
  try {
    const d = await api.dataset(name);
    const m = d.manifest || d.dataset || d;
    const st = m.statistics || {};
    el.innerHTML = `
      <div class="grid cols-4 section">
        <div class="stat hl"><div class="k">clips</div><div class="v">${st.total_files ?? '–'}</div></div>
        <div class="stat"><div class="k">fall</div><div class="v">${st.total_fall ?? '–'}</div></div>
        <div class="stat"><div class="k">adl</div><div class="v">${st.total_adl ?? '–'}</div></div>
        <div class="stat"><div class="k">avg duration</div><div class="v small">${st.avg_duration_seconds != null ? dec(st.avg_duration_seconds, 1) + ' s' : '–'}</div></div>
      </div>
      <div class="panel"><div class="muted-note">${esc(m.description || '')}</div>
        <div class="muted-note mt">input: ${esc(m.input_type || '')} · ground truth: ${esc(m.ground_truth_type || '')}
          ${/^https?:\/\//i.test(m.source_url || '') ? ` · <a href="${esc(m.source_url)}" target="_blank" rel="noopener">source</a>` : ''}</div></div>`;
  } catch (e) { el.innerHTML = empty('error', e.message || e); }
}
