// leakage.js — training-data provenance + data-leakage categories per
// (detector, dataset) pair. Transcribed from the thesis section "Mapa
// potencjalnego wycieku danych" (sec:leakage) and the detector table (tab:detektory).
//
// Category of a pair:
//   train   — dataset == detector's training set → memorisation, NOT generalisation.
//             Excluded from the generalisation mean (thesis H2).
//   eval    — dataset used to tune/design the detector (not final weights) → caution.
//   ood     — out-of-distribution → a fair cross-dataset generalisation test.
//   unknown — training data undocumented → status undeterminable, treat as conditional.
//
// Rule-based detectors (family C) have no learned component, so no memorisation
// leak is possible: every pair is `ood` (cwlroda is the exception — its bbox rules
// were tuned on URFD → that one pair is `eval`).

const URFD = 'ur_fall_detection';   // framework dataset id

// Per detector: training set(s) as framework ids where evaluated + a display name,
// optional tune[] (EVAL), `documented` flag, `ruleBased` flag.
export const PROVENANCE = {
  // Family A — pose + LSTM (learned)
  boboskyy_fall_detect:           { train: [URFD], trainName: 'URFD', documented: true },
  taufeeque_human_fall:           { train: ['up_fall'], trainName: 'UP-Fall', documented: true },
  // Family B — pose + TCN (learned)
  parichehrvn_tcn_fall:           { train: ['fall_sim'], trainName: 'Fall_Simulation_Data', documented: true },
  // Family F — pose + ST-GCN (learned action model)
  gajuuzz_stgcn:                  { train: ['le2i'], trainName: 'Le2i', documented: true },
  // Family C — pose + heuristics (rule-based, no training)
  cwlroda_openpifpaf:             { ruleBased: true, tune: [URFD], documented: true },
  barkhaaroraa_fall_detection_dl: { ruleBased: true, documented: true },
  yb_class_fall:                  { ruleBased: true, documented: true },
  itskyledc_yolov12_mediapipe:    { ruleBased: true, documented: true },
  // Family D — object detection (training data undocumented)
  noorkhokhar_yolov8_fall:        { documented: false },
  tonlongthuat_fall_detection:    { documented: false },
  // Family E — two-stream (training data undocumented)
  dzungvpham_twostream_cnn:       { documented: false },
};

export function provenance(det) {
  return PROVENANCE[det] || { documented: false };
}

// Category for a (detector, dataset) pair.
export function leakCategory(det, ds) {
  const p = provenance(det);
  if ((p.train || []).includes(ds)) return 'train';
  if ((p.tune || []).includes(ds)) return 'eval';
  if (p.documented === false) return 'unknown';
  return 'ood';
}

// Per-category display metadata. `tip` is an i18n key.
export const CAT = {
  train:   { mark: 'T', cls: 'train',   short: 'TRAIN', tip: 'leak_train_t' },
  eval:    { mark: 'E', cls: 'eval',    short: 'EVAL',  tip: 'leak_eval_t' },
  unknown: { mark: '?', cls: 'unknown', short: '?',     tip: 'leak_unknown_t' },
  ood:     { mark: '',  cls: 'ood',     short: 'OOD',   tip: 'leak_ood_t' },
};

// Human label for a detector's training data (for the detector-detail badge).
// Returns an i18n key OR a literal dataset name. Callers: literal if !startsWith('@').
export function trainingLabel(det) {
  const p = provenance(det);
  if (p.ruleBased) return '@prov_rule';
  if (p.documented === false) return '@prov_unknown';
  return p.trainName || '@prov_unknown';
}
