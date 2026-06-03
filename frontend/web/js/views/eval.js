// views/eval.js — a single evaluation by id (?id=eval-xxxx). Shows exactly the
// detector(s) and clips THAT run covered — including small 1–2 clip runs that
// the dataset-level leaderboard hides.
import { api } from '../api.js';
import { getResults } from '../store.js';
import { dsLabel, shortName, family, dec, ms, metricsFromCounts } from '../format.js';
import { stripedBar } from '../charts.js';
import { qs, esc, spinner, empty, toast } from '../components.js';
import { watchEvaluation } from '../live.js';
import { t } from '../i18n.js';
import { href, go } from '../router.js';

const STATUS_CLS = { completed: 'ok', partial: 'warn', failed: 'bad', cancelled: 'muted', running: 'info', pending: 'muted' };

function confusion(m) {
  return `<div class="cm" style="max-width:360px">
    <div class="cell hd"></div><div class="cell hd">pred FALL</div><div class="cell hd">pred ADL</div>
    <div class="cell hd">GT FALL</div><div class="cell tp"><div class="v">${m.tp}</div><div class="lab">TP</div></div><div class="cell fn"><div class="v">${m.fn}</div><div class="lab">FN</div></div>
    <div class="cell hd">GT ADL</div><div class="cell fp"><div class="v">${m.fp}</div><div class="lab">FP</div></div><div class="cell tn"><div class="v">${m.tn}</div><div class="lab">TN</div></div>
  </div>`;
}

export async function render(root, params) {
  const id = params.id;
  root.innerHTML = `<div class="eyebrow"><span class="n">06</span>EVALUATION</div>
    <h1 class="page-h"><span class="hash">#</span>${esc(id || '')}</h1>
    <div class="btn-row mb"><a class="btn ghost sm" href="${href('/evaluate')}">← ${esc(t('nav_evaluate'))}</a></div>
    <div id="ev-detail">${spinner('…')}</div>`;
  const el = qs('#ev-detail', root);
  if (!id) { el.innerHTML = empty('no evaluation id'); return; }

  let status;
  try { status = await api.evalStatus(id); }
  catch (e) { el.innerHTML = empty('evaluation not found', String(e.message || e)); return; }

  if (status.status === 'pending' || status.status === 'running') return renderLive(el, id, status);

  let res;
  try { res = await getResults(id); } catch (e) { el.innerHTML = empty('no results', String(e.message || e)); return; }
  renderResults(el, id, status, res);
}

function metaBar(status, res) {
  const cls = STATUS_CLS[status.status] || 'muted';
  const wall = res.total_wall_time_seconds != null ? ` · ${dec(res.total_wall_time_seconds, 1)} s` : '';
  return `<div class="row mb" style="gap:.6rem">
    <span class="badge ${cls}"><span class="dotled"></span>${esc(status.status)}</span>
    <a class="badge info" href="${href('/', { ds: status.dataset_name })}" style="text-decoration:none">${esc(dsLabel(status.dataset_name))} →</a>
    <span class="badge muted">${res.total_files_evaluated ?? status.completed_tasks} clips${wall}</span>
    <span class="badge muted">${status.completed_tasks}/${status.total_tasks} tasks${status.failed_tasks ? ' · ' + status.failed_tasks + ' failed' : ''}</span>
  </div>`;
}

function renderResults(el, id, status, res) {
  const summaries = (res.detector_summaries || []).slice();
  if (!summaries.length) { el.innerHTML = metaBar(status, res) + empty('no detector results', 'This run produced no labeled results.'); return; }

  summaries.sort((a, b) => b.f1_score - a.f1_score);
  const rowsForFiles = summaries;

  let detBlocks;
  if (summaries.length === 1) {
    const sm = summaries[0];
    const m = metricsFromCounts(sm.true_positives, sm.true_negatives, sm.false_positives, sm.false_negatives);
    detBlocks = `
      <div class="row between mb"><h2 class="sec-h" style="margin:0"><span class="fam" style="margin-right:.4rem">${family(sm.detector_name)}</span>${esc(shortName(sm.detector_name))}<span class="rule"></span></h2>
        <a class="btn ghost sm" href="${href('/detectors', { name: sm.detector_name })}">detector →</a></div>
      <div class="grid cols-4 section">
        <div class="stat hl"><div class="k">F1</div><div class="v">${dec(m.f1)}</div></div>
        <div class="stat"><div class="k">precision</div><div class="v">${dec(m.precision)}</div></div>
        <div class="stat"><div class="k">recall</div><div class="v">${dec(m.recall)}</div></div>
        <div class="stat"><div class="k">FPR</div><div class="v">${dec(m.fpr)}</div></div>
      </div>
      <div class="grid cols-2 section" style="align-items:start">
        <div class="panel"><div class="panel-h">confusion</div>${confusion(m)}</div>
        <div class="panel"><div class="panel-h">acc ${dec(m.accuracy)} · avg ${ms(sm.avg_processing_time_ms)}</div>
          <div class="muted-note">${m.labeled} labeled clips · TP ${m.tp} · TN ${m.tn} · FP ${m.fp} · FN ${m.fn}</div></div>
      </div>`;
  } else {
    const maxF1 = Math.max(...summaries.map(s => s.f1_score));
    detBlocks = `<h2 class="sec-h">detectors · F1<span class="rule"></span></h2>
      <div class="panel section"><div class="lb">${summaries.map((sm, i) => {
        const m = metricsFromCounts(sm.true_positives, sm.true_negatives, sm.false_positives, sm.false_negatives);
        return `<a class="lb-row ${i === 0 ? 'best' : ''}" href="${href('/detectors', { name: sm.detector_name })}">
          <div class="rank r${i + 1}">${i + 1}</div>
          <div class="lb-name"><span class="fam">${family(sm.detector_name)}</span><span class="nm">${esc(shortName(sm.detector_name))}</span></div>
          ${stripedBar(sm.f1_score, { max: 1, best: i === 0 })}
          <div class="lb-val">${dec(sm.f1_score)}<span class="secd num">R ${dec(m.recall, 2)} · FPR ${dec(m.fpr, 2)}</span></div>
        </a>`;
      }).join('')}</div></div>`;
  }

  // per-clip table (this run's actual clips)
  const flat = [];
  for (const sm of rowsForFiles) for (const r of sm.per_file_results || []) flat.push({ d: shortName(sm.detector_name), r });
  const clipRows = flat.map(({ d, r }) => `<tr>
    <td class="mono">${esc(r.filename)}</td>
    <td><span class="badge ${r.ground_truth_label === 'FALL' ? 'warn' : 'muted'}">${esc(r.ground_truth_label)}</span></td>
    <td class="mono">${esc(d)}</td>
    <td class="mono ${(r.detector_verdict === 'FALL' || r.detector_verdict === true) ? 'acc' : 'dim'}">${(r.detector_verdict === 'FALL' || r.detector_verdict === true) ? 'FALL' : 'ADL'}</td>
    <td>${r.classification ? `<span class="cls ${r.classification}">${r.classification}</span>` : '<span class="cls dim">·</span>'}</td>
    <td class="num">${r.detector_fall_frame_count}</td><td class="num dim">${r.detector_total_frames}</td>
    <td class="num">${r.detector_confidence != null ? dec(r.detector_confidence, 2) : '–'}</td>
    <td class="num dim">${r.processing_time_ms}</td>
  </tr>`).join('');

  el.innerHTML = metaBar(status, res) + detBlocks + `
    <div class="panel"><div class="panel-h">clips in this run <span class="dim">· ${flat.length} rows</span></div>
      <div class="tbl-wrap"><table class="tbl">
        <thead><tr><th>clip</th><th>GT</th><th>detector</th><th>verdict</th><th>cls</th>
          <th class="num">fall_frames</th><th class="num">frames</th><th class="num">conf</th><th class="num">ms</th></tr></thead>
        <tbody>${clipRows}</tbody></table></div></div>`;
}

let liveStop = null;
function renderLive(el, id, status) {
  if (liveStop) { liveStop(); liveStop = null; }
  const draw = (s) => {
    const pctv = s.progress_pct ?? (s.total_tasks ? s.completed_tasks / s.total_tasks * 100 : 0);
    const done = ['completed', 'partial', 'failed', 'cancelled'].includes(s.status);
    el.innerHTML = `<div class="live-banner section">
      <div class="live-head">${done ? '' : '<span class="pulse"></span>'}<span>${esc(dsLabel(s.dataset_name))} · ${(s.detector_names || []).map(shortName).join(', ')}</span>
        <span class="spread"></span><span class="mono acc">${dec(pctv, 0)}%</span>
        <span class="mono dim">${s.completed_tasks ?? 0}/${s.total_tasks ?? '?'}</span></div>
      ${stripedBar(pctv / 100, { best: s.status === 'completed' })}
      <div class="btn-row">${['pending', 'running'].includes(s.status) ? `<button class="btn sm danger" id="cancel">${esc(t('cancel'))}</button>` : ''}</div>
    </div>`;
    const c = qs('#cancel', el);
    if (c) c.addEventListener('click', async () => { try { await api.cancelEval(id); toast('cancel requested', 'info'); } catch (e) { toast(e.message, 'err'); } });
  };
  draw(status);
  liveStop = watchEvaluation(id, { onUpdate: draw, onDone: () => go(href('/eval', { id }).slice(1)) });
}
