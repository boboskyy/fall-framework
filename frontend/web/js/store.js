// store.js — caches gateway data and reconstructs the multi-detector picture
// from the single-detector evaluations the gateway actually stores.
import { api } from './api.js';
import { metricsFromCounts, family, shortName, classifyAt } from './format.js';

const cache = { datasets: null, evals: null, results: new Map() };

export async function getDatasets(force) {
  if (!cache.datasets || force) {
    const d = await api.datasets();
    cache.datasets = Array.isArray(d) ? d : (d.datasets || []);
  }
  return cache.datasets;
}
export async function getEvals(force) {
  if (!cache.evals || force) {
    const d = await api.evaluations();
    cache.evals = (d.evaluations || []).slice();
  }
  return cache.evals;
}
export async function getResults(id) {
  if (!cache.results.has(id)) cache.results.set(id, await api.evalResults(id));
  return cache.results.get(id);
}
export function invalidate() { cache.evals = null; cache.results.clear(); }

const score = (e) => (e.status === 'completed' ? 1e9 : 0) + (e.completed_tasks || 0);

// For a dataset, choose the best eval per detector (completed preferred, most
// clips, latest), fetch results, and build merged leaderboard rows.
export async function leaderboard(dataset) {
  const evals = await getEvals();
  const onDs = evals.filter(e => e.dataset_name === dataset &&
                                 (e.status === 'completed' || e.status === 'partial'));
  // pick winning eval per detector
  const pick = new Map(); // detector -> eval
  for (const e of onDs) {
    for (const det of e.detector_names) {
      const cur = pick.get(det);
      if (!cur || score(e) > score(cur) ||
          (score(e) === score(cur) && e.created_at > cur.created_at)) pick.set(det, e);
    }
  }
  // fetch results for the chosen evals (dedup by eval id)
  const needed = [...new Set([...pick.values()].map(e => e.eval_id))];
  const resById = {};
  await Promise.all(needed.map(async id => { try { resById[id] = await getResults(id); } catch {} }));

  const rows = [];
  let verdictConfig = null;
  for (const [det, e] of pick) {
    const res = resById[e.eval_id];
    if (!res) continue;
    verdictConfig = verdictConfig || res.verdict_config;
    const sm = (res.detector_summaries || []).find(s => s.detector_name === det);
    if (!sm) continue;
    const m = metricsFromCounts(sm.true_positives, sm.true_negatives,
                                sm.false_positives, sm.false_negatives);
    rows.push({
      name: det, short: shortName(det), family: family(det),
      evalId: e.eval_id, status: e.status,
      summary: sm, ...m,
      avgTime: sm.avg_processing_time_ms,
      perFile: sm.per_file_results || [],
      partial: e.status === 'partial',
    });
  }
  rows.sort((a, b) => b.f1 - a.f1);
  return { dataset, rows, verdictConfig, evalsOnDataset: onDs.length };
}

export function bestPerMetric(rows) {
  if (!rows.length) return {};
  const by = (k, dir = 1) => rows.reduce((a, b) => (dir * (b[k] - a[k]) > 0 ? b : a));
  return {
    f1: by('f1'), recall: by('recall'), precision: by('precision'),
    fpr: by('fpr', -1), accuracy: by('accuracy'),
  };
}

// Per-clip matrix across detectors (for strip / κ / threshold-across-detectors).
export function perFileMatrix(rows) {
  const clips = new Map(); // filename -> { gt, byDet:{det:r} }
  for (const row of rows) {
    for (const r of row.perFile) {
      if (!clips.has(r.filename)) clips.set(r.filename, { filename: r.filename, gt: r.ground_truth_fall, byDet: {} });
      clips.get(r.filename).byDet[row.name] = r;
    }
  }
  return { detectors: rows.map(r => r.name), clips: [...clips.values()] };
}

// Cohen's κ on binary error vectors (1 = detector wrong) at threshold k.
export function kappa(rowA, rowB, k = 1) {
  const aMap = new Map(rowA.perFile.map(r => [r.filename, r]));
  let n = 0, both = 0, a1 = 0, b1 = 0, agree = 0, bothWrong = 0;
  for (const rb of rowB.perFile) {
    const ra = aMap.get(rb.filename);
    if (!ra) continue;
    const ca = classifyAt(ra, k), cb = classifyAt(rb, k);
    if (ca == null || cb == null) continue;
    const ea = (ca === 'FP' || ca === 'FN') ? 1 : 0;
    const eb = (cb === 'FP' || cb === 'FN') ? 1 : 0;
    n++; a1 += ea; b1 += eb;
    if (ea === eb) agree++;
    if (ea && eb) bothWrong++;
    both++;
  }
  if (!n) return { k: null, df: null, n: 0 };
  const po = agree / n;
  const pa1 = a1 / n, pb1 = b1 / n;
  const pe = pa1 * pb1 + (1 - pa1) * (1 - pb1);
  const kap = pe === 1 ? 0 : (po - pe) / (1 - pe);
  return { k: kap, df: bothWrong / n, n, bothWrong };
}

export const datasetsCache = () => cache.datasets;
