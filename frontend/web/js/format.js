// format.js — detector taxonomy, number formatting, metric math.
import { lang } from './i18n.js';

/* ----- detector taxonomy (thesis families A–F) ----- */
export const FAMILY = {
  taufeeque_human_fall: 'A', boboskyy_fall_detect: 'A',
  parichehrvn_tcn_fall: 'B',
  cwlroda_openpifpaf: 'C', barkhaaroraa_fall_detection_dl: 'C',
  yb_class_fall: 'C', itskyledc_yolov12_mediapipe: 'C',
  noorkhokhar_yolov8_fall: 'D', tonlongthuat_fall_detection: 'D',
  dzungvpham_twostream_cnn: 'E',
  gajuuzz_stgcn: 'F',
};
export const FAMILY_LABEL = {
  A: 'pose → LSTM', B: 'pose → TCN', C: 'pose → heuristic',
  D: 'object detection', E: 'two-stream CNN', F: 'ST-GCN',
};
const SHORT = {
  taufeeque_human_fall: 'taufeeque', boboskyy_fall_detect: 'boboskyy',
  parichehrvn_tcn_fall: 'parichehrvn', cwlroda_openpifpaf: 'cwlroda',
  barkhaaroraa_fall_detection_dl: 'barkhaaroraa', yb_class_fall: 'yb_class',
  itskyledc_yolov12_mediapipe: 'itskyledc', noorkhokhar_yolov8_fall: 'noorkhokhar',
  tonlongthuat_fall_detection: 'tonlongthuat', dzungvpham_twostream_cnn: 'dzungvpham',
  gajuuzz_stgcn: 'gajuuzz',
};
export const family = (n) => FAMILY[n] || '?';
export const shortName = (n) => SHORT[n] || (n || '').split('_')[0];

const DS_LABEL = {
  ur_fall_detection: 'URFD', gmdcsa24: 'GMDCSA-24',
  caucafall: 'CAUCAFall', mcfd: 'MCFD',
};
export const dsLabel = (n) => DS_LABEL[n] || n;

/* ----- numbers ----- */
export function dec(x, p = 3) {
  if (x === null || x === undefined || Number.isNaN(x)) return '–';
  const s = Number(x).toFixed(p);
  return lang() === 'pl' ? s.replace('.', ',') : s;
}
export function pct(x, p = 1) {
  if (x === null || x === undefined || Number.isNaN(x)) return '–';
  return dec(x * 100, p) + '%';
}
export function int(x) {
  if (x === null || x === undefined) return '–';
  return String(x);
}
export function ms(x) {
  if (x === null || x === undefined) return '–';
  if (x >= 1000) return dec(x / 1000, 2) + ' s';
  return Math.round(x) + ' ms';
}
export function ago(iso) {
  if (!iso) return '–';
  const then = new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime();
  const d = (Date.now() - then) / 1000;
  if (d < 60) return Math.round(d) + 's';
  if (d < 3600) return Math.round(d / 60) + 'm';
  if (d < 86400) return Math.round(d / 3600) + 'h';
  return Math.round(d / 86400) + 'd';
}

/* ----- metric math -----
   A "row" is { tp, tn, fp, fn } from confusion counts.                     */
export function metricsFromCounts(tp, tn, fp, fn) {
  const labeled = tp + tn + fp + fn;
  const accuracy = labeled ? (tp + tn) / labeled : 0;
  const precision = (tp + fp) ? tp / (tp + fp) : 0;
  const recall = (tp + fn) ? tp / (tp + fn) : 0;
  const f1 = (precision + recall) ? 2 * precision * recall / (precision + recall) : 0;
  const fpr = (fp + tn) ? fp / (fp + tn) : 0;
  const specificity = (tn + fp) ? tn / (tn + fp) : 0;
  return { tp, tn, fp, fn, labeled, accuracy, precision, recall, f1, fpr, specificity };
}

/* Recompute one detector's confusion at an arbitrary verdict threshold
   (verdict = fall_frame_count >= k) from its per_file_results.            */
export function countsAtThreshold(perFile, k) {
  let tp = 0, tn = 0, fp = 0, fn = 0;
  for (const r of perFile) {
    if (r.ground_truth_fall === null || r.ground_truth_fall === undefined) continue;
    const verdict = (r.detector_fall_frame_count || 0) >= k;
    const gt = !!r.ground_truth_fall;
    if (gt && verdict) tp++;
    else if (!gt && !verdict) tn++;
    else if (!gt && verdict) fp++;
    else fn++;
  }
  return metricsFromCounts(tp, tn, fp, fn);
}

/* classification of a single clip at threshold k */
export function classifyAt(r, k) {
  if (r.ground_truth_fall === null || r.ground_truth_fall === undefined) return null;
  const verdict = (r.detector_fall_frame_count || 0) >= k;
  const gt = !!r.ground_truth_fall;
  if (gt && verdict) return 'TP';
  if (!gt && !verdict) return 'TN';
  if (!gt && verdict) return 'FP';
  return 'FN';
}

export const MAX_THRESHOLD = 30;
