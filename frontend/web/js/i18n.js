// i18n.js — lightweight PL/EN for UI chrome (proj- style). Metric abbreviations
// (F1, FPR, TP…) stay language-neutral.
const DICT = {
  pl: {
    nav_lab: 'Lab', nav_threshold: 'Próg', nav_diversity: 'Różnorodność',
    nav_files: 'Klipy', nav_matrix: 'Macierz', nav_evaluate: 'Ewaluacja',
    nav_detectors: 'Detektory', nav_datasets: 'Zbiory',
    lab_h: 'Pracownia ewaluacji', lab_sub: 'Skuteczność detektorów upadków na żywo z bramy — ranking, progi i współdzielone błędy.',
    last_run: 'ostatni przebieg', detectors: 'detektorów', clips: 'klipów',
    best_f1: 'Najlepszy F1', best_recall: 'Najlepszy recall', lowest_fpr: 'Najniższy FPR', best_prec: 'Najlepsza precyzja',
    ranking: 'Ranking', no_data: 'Brak danych',
    lab_balance: 'fall / adl', lab_avgf1: 'śr. F1', lab_evals_total: 'ewaluacje (Σ)', lab_datasets: 'zbiory z danymi',
    add_dataset: 'Dodaj zbiór', add_detector: 'Dodaj detektor', upload_zip: 'Wgraj .zip', refresh_registry: 'Odśwież rejestr',
    rescan: 'Przeskanuj', template: 'Szablon detektora', scope_all: 'cały zbiór', scope_pick: 'wybierz klipy', files_picked: 'wybranych klipów',
    no_evals_h: 'Brak ewaluacji dla tego zbioru', no_evals_b: 'Uruchom ewaluację, aby zobaczyć ranking.',
    run_eval: 'Uruchom ewaluację', view: 'Zobacz', open: 'Otwórz',
    system: 'system', healthy: 'sprawne', gateway_ok: 'brama ok', gateway_down: 'brama niedostępna',
    th_h: 'Wrażliwość na próg werdyktu', th_sub: 'Werdykt = liczba klatek-upadku ≥ próg. Wszystko przeliczane na żywo z fall_frames — bez ponownej ewaluacji.',
    f1_curve: 'F1 w funkcji progu', ff_hist: 'Rozkład fall_frames', leaderboard_at: 'Ranking przy progu',
    div_h: 'Współdzielone błędy i różnorodność', div_sub: 'Macierz κ (Cohena) na wektorach błędów + eksplorator double-fault. Liczone z per-klip werdyktów.',
    kappa_matrix: 'Macierz κ (zgodność błędów)', double_fault: 'Double-fault — kandydaci do zespołu',
    files_h: 'Wyniki per klip', files_sub: 'Pasek zgodności + tabela z filtrami. Eksport do CSV.', agreement_strip: 'Pasek zgodności (wiersz = klip)',
    matrix_h: 'Macierz międzydatasetowa', matrix_sub: 'F1 detektor × zbiór z rangami. Inny lider na każdym zbiorze = brak uniwersalnie najlepszego.',
    matrix_leader: 'lider per zbiór', matrix_legend: 'ranga w zbiorze · ⌀ = średnia F1',
    matrix_reshuffle: 'Inny lider na różnych zbiorach → brak uniwersalnie najlepszego detektora (teza pracy).',
    matrix_same: 'Ten sam detektor prowadzi wszędzie (przy obecnych danych) — oceń więcej detektorów na pozostałych zbiorach, by zobaczyć przetasowanie.',
    eval_h: 'Nowa ewaluacja', eval_sub: 'Wybierz zbiór i detektory, uruchom i obserwuj postęp na żywo.', dataset: 'Zbiór', start: 'Start', running: 'w toku', queued: 'w kolejce', done: 'gotowe', failed: 'błąd', cancel: 'Przerwij', cancelled: 'przerwane', progress: 'postęp',
    detectors_h: 'Detektory', datasets_h: 'Zbiory danych', health: 'stan', family: 'rodzina', category: 'kategoria',
    export_csv: 'Eksport CSV', export_png: 'Eksport PNG', filter: 'Filtr', all: 'wszystkie', errors_only: 'tylko błędy',
    system_h: 'System — kontenery i brama', start_c: 'Start', stop_c: 'Stop', build_c: 'Build',
    select_detectors: 'Wybierz detektory', select_all: 'wszystkie', clear: 'wyczyść',
    metric: 'Metryka', value: 'Wartość',
  },
  en: {
    nav_lab: 'Lab', nav_threshold: 'Threshold', nav_diversity: 'Diversity',
    nav_files: 'Clips', nav_matrix: 'Matrix', nav_evaluate: 'Evaluate',
    nav_detectors: 'Detectors', nav_datasets: 'Datasets',
    lab_h: 'Evaluation Lab', lab_sub: 'Live fall-detector performance from the gateway — ranking, thresholds and shared errors.',
    last_run: 'last run', detectors: 'detectors', clips: 'clips',
    best_f1: 'Best F1', best_recall: 'Best recall', lowest_fpr: 'Lowest FPR', best_prec: 'Best precision',
    ranking: 'Ranking', no_data: 'No data',
    lab_balance: 'fall / adl', lab_avgf1: 'avg F1', lab_evals_total: 'evaluations (Σ)', lab_datasets: 'datasets with data',
    add_dataset: 'Add dataset', add_detector: 'Add detector', upload_zip: 'Upload .zip', refresh_registry: 'Refresh registry',
    rescan: 'Rescan', template: 'Detector template', scope_all: 'whole dataset', scope_pick: 'pick clips', files_picked: 'clips picked',
    no_evals_h: 'No evaluations for this dataset', no_evals_b: 'Run an evaluation to see the ranking.',
    run_eval: 'Run evaluation', view: 'View', open: 'Open',
    system: 'system', healthy: 'healthy', gateway_ok: 'gateway ok', gateway_down: 'gateway down',
    th_h: 'Verdict threshold sensitivity', th_sub: 'Verdict = fall-frame count ≥ threshold. Everything recomputes live from fall_frames — no re-evaluation.',
    f1_curve: 'F1 vs threshold', ff_hist: 'fall_frames distribution', leaderboard_at: 'Ranking at threshold',
    div_h: 'Shared errors & diversity', div_sub: "Cohen's κ matrix on error vectors + double-fault explorer. Computed from per-clip verdicts.",
    kappa_matrix: 'κ matrix (error agreement)', double_fault: 'Double-fault — ensemble candidates',
    files_h: 'Per-clip results', files_sub: 'Agreement strip + filterable table. Export to CSV.', agreement_strip: 'Agreement strip (row = clip)',
    matrix_h: 'Cross-dataset matrix', matrix_sub: 'Detector × dataset F1 with ranks. A different leader per dataset = no universal winner.',
    matrix_leader: 'leader per dataset', matrix_legend: 'rank within dataset · ⌀ = mean F1',
    matrix_reshuffle: 'Different leader across datasets → no universally best detector (the thesis point).',
    matrix_same: 'Same detector leads everywhere (with current data) — evaluate more detectors on the other datasets to see the reshuffle.',
    eval_h: 'New evaluation', eval_sub: 'Pick a dataset and detectors, launch and watch progress live.', dataset: 'Dataset', start: 'Start', running: 'running', queued: 'queued', done: 'done', failed: 'failed', cancel: 'Cancel', cancelled: 'cancelled', progress: 'progress',
    detectors_h: 'Detectors', datasets_h: 'Datasets', health: 'health', family: 'family', category: 'category',
    export_csv: 'Export CSV', export_png: 'Export PNG', filter: 'Filter', all: 'all', errors_only: 'errors only',
    system_h: 'System — containers & gateway', start_c: 'Start', stop_c: 'Stop', build_c: 'Build',
    select_detectors: 'Select detectors', select_all: 'all', clear: 'clear',
    metric: 'Metric', value: 'Value',
  },
};

let _lang = (() => { try { return localStorage.getItem('fallfw_lang') || 'en'; } catch { return 'en'; } })();
const _subs = new Set();

export function lang() { return _lang; }
export function setLang(l) {
  if (!DICT[l]) return;
  _lang = l;
  try { localStorage.setItem('fallfw_lang', l); } catch {}
  document.documentElement.lang = l;
  _subs.forEach(fn => fn());
}
export function onLang(fn) { _subs.add(fn); return () => _subs.delete(fn); }
export function t(key) { return (DICT[_lang] && DICT[_lang][key]) || (DICT.en[key]) || key; }
