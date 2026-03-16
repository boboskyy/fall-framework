
import csv
import io
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from gateway.dataset_models import (
    DatasetFile, DatasetManifest, EvaluationFileResult,
    EvaluationDetectorSummary, EvaluationJob, EvaluationResult,
)
from gateway.dataset_manager import DatasetManager


def compute_video_verdict(detection_result: dict,
                          min_fall_frames: int = 1,
                          min_fall_percentage: float = 0.0) -> dict:
    """Derive video-level FALL/ADL verdict from frame-level detection results.

    Takes a raw dict (as stored in SubTask.result by the orchestrator),
    NOT a DetectionResponse dataclass.
    """
    frame_results = detection_result.get('frame_results', [])
    fall_frames = [fr for fr in frame_results if fr.get('fall_detected', False)]
    total = len(frame_results)
    fall_count = len(fall_frames)
    fall_pct = fall_count / total if total > 0 else 0.0

    verdict = (fall_count >= min_fall_frames) and (fall_pct >= min_fall_percentage)

    def _get_confidence(fr):
        for key in ('fall_confidence', 'confidence', 'max_confidence'):
            if key in fr and fr[key] is not None:
                return fr[key]
        persons = fr.get('persons', [])
        if persons:
            return persons[0].get('fall_confidence')
        return None

    confidences = [c for c in (_get_confidence(fr) for fr in fall_frames) if c is not None]

    return {
        'verdict': verdict,
        'fall_frame_count': fall_count,
        'total_frames': total,
        'fall_percentage': round(fall_pct, 4),
        'max_confidence': max(confidences) if confidences else None,
        'first_fall_frame': fall_frames[0].get('frame_index') if fall_frames else None,
        'last_fall_frame': fall_frames[-1].get('frame_index') if fall_frames else None,
    }


class EvaluationManager:

    def __init__(self, dataset_manager: DatasetManager,
                 orchestrator, comparison_engine):
        self.dataset_manager = dataset_manager
        self.orchestrator = orchestrator
        self.comparison_engine = comparison_engine
        self._evaluations: Dict[str, EvaluationJob] = {}

    def create_evaluation(self, dataset_name: str,
                          detector_names: List[str],
                          selected_files: List[str] = None,
                          config: dict = None,
                          verdict_config: dict = None,
                          sync: bool = False) -> Dict:
        manifest = self.dataset_manager._datasets.get(dataset_name)
        if not manifest:
            return {'error': 'NOT_FOUND', 'message': f'Dataset "{dataset_name}" not found'}

        validation = self.orchestrator.registry.validate_detectors(
            detector_names, manifest.input_type
        )
        if not validation['valid']:
            return {
                'error': 'INVALID_DETECTORS',
                'message': '; '.join(validation['errors']),
            }

        if selected_files:
            file_map = {f.filename: f for f in manifest.files}
            missing = [fn for fn in selected_files if fn not in file_map]
            if missing:
                return {
                    'error': 'FILES_NOT_FOUND',
                    'message': f'Files not in dataset: {", ".join(missing)}',
                }
            eval_files = [file_map[fn] for fn in selected_files]
        else:
            eval_files = list(manifest.files)

        labeled = [f for f in eval_files if f.label != 'UNLABELED']
        if not labeled and manifest.ground_truth_type != 'none':
            all_unlabeled = all(f.label == 'UNLABELED' for f in eval_files)
            if all_unlabeled:
                return {
                    'error': 'NO_LABELED_FILES',
                    'message': 'All selected files are unlabeled — cannot compute metrics',
                }

        vc = verdict_config or {}
        min_fall_frames = vc.get('min_fall_frames', 1)
        min_fall_pct = vc.get('min_fall_percentage', 0.0)

        eval_id = f'eval-{uuid.uuid4().hex[:8]}'
        total_tasks = len(eval_files) * len(detector_names)

        job = EvaluationJob(
            eval_id=eval_id,
            dataset_name=dataset_name,
            detector_names=detector_names,
            selected_files=[f.filename for f in eval_files],
            config=config,
            verdict_config={
                'min_fall_frames': min_fall_frames,
                'min_fall_percentage': min_fall_pct,
            },
            total_tasks=total_tasks,
        )
        self._evaluations[eval_id] = job

        if sync:
            self._run_evaluation(job, manifest, eval_files)
            result = job.result.to_dict() if job.result else job.to_dict()
            return result
        else:
            thread = threading.Thread(
                target=self._run_evaluation,
                args=(job, manifest, eval_files),
                daemon=True,
            )
            thread.start()
            return {
                'eval_id': eval_id,
                'status': 'pending',
                'dataset': dataset_name,
                'detectors': detector_names,
                'total_tasks': total_tasks,
                'message': 'Evaluation started',
            }

    def _run_evaluation(self, job: EvaluationJob, manifest: DatasetManifest,
                        eval_files: List[DatasetFile]):
        start_time = time.time()
        job.status = 'running'
        job.started_at = datetime.utcnow().isoformat()

        try:
            shared_base = self.dataset_manager.prepare_for_evaluation(
                job.eval_id, job.dataset_name,
                [f.filename for f in eval_files],
            )
        except Exception as e:
            job.status = 'failed'
            job.error = f'Failed to prepare files: {str(e)}'
            job.completed_at = datetime.utcnow().isoformat()
            return

        # Per-detector, per-file results
        # Structure: detector_name → [EvaluationFileResult, ...]
        detector_file_results: Dict[str, List[EvaluationFileResult]] = {
            d: [] for d in job.detector_names
        }

        for df in eval_files:
            if job.cancelled:
                break

            input_path = f'{shared_base}/{df.filename}'

            result = self.orchestrator.submit_multi(
                input_path=input_path,
                input_type=manifest.input_type,
                detector_names=job.detector_names,
                config=job.config,
                sync=True,
            )

            if 'error' in result:
                for det in job.detector_names:
                    task_key = f'{df.filename}::{det}'
                    job.sub_tasks[task_key] = {
                        'status': 'failed',
                        'error': result.get('message', result['error']),
                    }
                    job.failed_tasks += 1
                continue

            orch_job = self.orchestrator.get_job(result['job_id'])
            if not orch_job:
                continue

            for det in job.detector_names:
                task_key = f'{df.filename}::{det}'
                sub = orch_job.sub_tasks.get(det)

                if not sub or sub.status != 'completed' or not sub.result:
                    job.sub_tasks[task_key] = {
                        'status': 'failed',
                        'error': sub.error if sub else 'No result',
                    }
                    job.failed_tasks += 1
                    continue

                file_result = self._compute_file_result(
                    df, sub.result, det, job.verdict_config,
                    manifest.ground_truth_type,
                )
                detector_file_results[det].append(file_result)

                job.sub_tasks[task_key] = {'status': 'completed'}
                job.completed_tasks += 1

        # Compute summaries
        detector_summaries = []
        for det in job.detector_names:
            results_list = detector_file_results[det]
            if results_list:
                summary = self._compute_detector_summary(det, results_list)
                detector_summaries.append(summary)

        # Cross-detector agreement
        cross_agreement = None
        if len(detector_summaries) > 1:
            cross_agreement = self._compute_cross_detector_agreement(
                detector_summaries, eval_files,
            )

        # Overall statistics
        overall = self._compute_overall_statistics(detector_summaries)

        wall_time = time.time() - start_time

        if job.cancelled:
            processed_file_count = len(set(k.split('::')[0] for k in job.sub_tasks))
        else:
            processed_file_count = len(eval_files)

        eval_result = EvaluationResult(
            eval_id=job.eval_id,
            dataset_name=job.dataset_name,
            ground_truth_type=manifest.ground_truth_type,
            total_files_evaluated=processed_file_count,
            total_files_in_dataset=len(manifest.files),
            selected_files=job.selected_files,
            verdict_config=job.verdict_config,
            detector_summaries=detector_summaries,
            cross_detector_agreement=cross_agreement,
            overall_statistics=overall,
            created_at=job.created_at,
            completed_at=datetime.utcnow().isoformat(),
            total_wall_time_seconds=round(wall_time, 1),
            status='cancelled' if job.cancelled else 'completed',
        )

        job.result = eval_result
        job.completed_at = eval_result.completed_at

        if job.cancelled:
            job.status = 'cancelled'
        elif job.failed_tasks == 0:
            job.status = 'completed'
        elif job.completed_tasks == 0:
            job.status = 'failed'
        else:
            job.status = 'partial'

        # Cleanup copied files
        self.dataset_manager.cleanup_evaluation(job.eval_id)

    def _compute_file_result(self, dataset_file: DatasetFile,
                             detection_result: dict, detector_name: str,
                             verdict_config: dict,
                             ground_truth_type: str) -> EvaluationFileResult:
        verdict_info = compute_video_verdict(
            detection_result,
            min_fall_frames=verdict_config.get('min_fall_frames', 1),
            min_fall_percentage=verdict_config.get('min_fall_percentage', 0.0),
        )

        detector_verdict = verdict_info['verdict']
        gt_fall = dataset_file.fall_detected_ground_truth
        gt_label = dataset_file.label

        match = None
        classification = None
        if gt_fall is not None:
            match = (gt_fall == detector_verdict)
            if gt_fall and detector_verdict:
                classification = 'TP'
            elif not gt_fall and not detector_verdict:
                classification = 'TN'
            elif not gt_fall and detector_verdict:
                classification = 'FP'
            elif gt_fall and not detector_verdict:
                classification = 'FN'

        processing_time = detection_result.get('processing_time_ms', 0)

        frame_metrics = None
        if ground_truth_type == 'frame_level' and dataset_file.annotations_path:
            frame_metrics = self._compute_frame_level_metrics(
                dataset_file, detection_result,
            )

        return EvaluationFileResult(
            filename=dataset_file.filename,
            ground_truth_label=gt_label,
            ground_truth_fall=gt_fall,
            detector_verdict=detector_verdict,
            detector_confidence=verdict_info['max_confidence'],
            detector_fall_frame_count=verdict_info['fall_frame_count'],
            detector_total_frames=verdict_info['total_frames'],
            detector_fall_percentage=verdict_info['fall_percentage'],
            match=match,
            classification=classification,
            processing_time_ms=int(processing_time),
            frame_level_metrics=frame_metrics,
        )

    def _compute_detector_summary(self, detector_name: str,
                                  file_results: List[EvaluationFileResult]) -> EvaluationDetectorSummary:
        tp = sum(1 for r in file_results if r.classification == 'TP')
        tn = sum(1 for r in file_results if r.classification == 'TN')
        fp = sum(1 for r in file_results if r.classification == 'FP')
        fn = sum(1 for r in file_results if r.classification == 'FN')
        labeled_count = tp + tn + fp + fn

        accuracy = (tp + tn) / labeled_count if labeled_count > 0 else 0.0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        times = [r.processing_time_ms for r in file_results]
        avg_time = sum(times) / len(times) if times else 0.0
        total_time = sum(times)

        # Frame-level averages
        frame_metrics_list = [r.frame_level_metrics for r in file_results
                              if r.frame_level_metrics is not None]
        avg_fp = None
        avg_fr = None
        avg_ff = None
        avg_iou = None
        if frame_metrics_list:
            avg_fp = round(sum(m.get('precision', 0) for m in frame_metrics_list) / len(frame_metrics_list), 4)
            avg_fr = round(sum(m.get('recall', 0) for m in frame_metrics_list) / len(frame_metrics_list), 4)
            avg_ff = round(sum(m.get('f1', 0) for m in frame_metrics_list) / len(frame_metrics_list), 4)
            avg_iou = round(sum(m.get('temporal_iou', 0) for m in frame_metrics_list) / len(frame_metrics_list), 4)

        return EvaluationDetectorSummary(
            detector_name=detector_name,
            total_files=len(file_results),
            true_positives=tp,
            true_negatives=tn,
            false_positives=fp,
            false_negatives=fn,
            accuracy=round(accuracy, 4),
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1_score=round(f1, 4),
            avg_processing_time_ms=round(avg_time, 1),
            total_processing_time_ms=int(total_time),
            avg_frame_precision=avg_fp,
            avg_frame_recall=avg_fr,
            avg_frame_f1=avg_ff,
            avg_temporal_iou=avg_iou,
            per_file_results=file_results,
        )

    def _compute_cross_detector_agreement(self, summaries: List[EvaluationDetectorSummary],
                                          eval_files: List[DatasetFile]) -> Dict:
        # Build verdict map: filename → detector → verdict
        verdict_map: Dict[str, Dict[str, bool]] = {}
        for summary in summaries:
            for fr in summary.per_file_results:
                if fr.filename not in verdict_map:
                    verdict_map[fr.filename] = {}
                verdict_map[fr.filename][summary.detector_name] = fr.detector_verdict

        det_names = [s.detector_name for s in summaries]

        # Pairwise agreement
        pairwise = {}
        for i, d1 in enumerate(det_names):
            for j, d2 in enumerate(det_names):
                if i >= j:
                    continue
                agree = 0
                total = 0
                for fn, verdicts in verdict_map.items():
                    if d1 in verdicts and d2 in verdicts:
                        total += 1
                        if verdicts[d1] == verdicts[d2]:
                            agree += 1
                key = f'{d1}_vs_{d2}'
                pairwise[key] = round(agree / total, 4) if total > 0 else 0.0

        avg_agreement = round(sum(pairwise.values()) / len(pairwise), 4) if pairwise else 0.0

        # Unanimous / split
        unanimous = 0
        split = 0
        per_file_verdicts = {}
        file_gt_map = {f.filename: f for f in eval_files}

        for fn, verdicts in verdict_map.items():
            vals = list(verdicts.values())
            is_unanimous = len(set(vals)) <= 1

            gt_file = file_gt_map.get(fn)
            gt_label = gt_file.label if gt_file else 'UNLABELED'

            per_file_verdicts[fn] = {
                'ground_truth': gt_label,
                **verdicts,
                'unanimous': is_unanimous,
            }

            if is_unanimous:
                unanimous += 1
            else:
                split += 1

        # Best / worst by F1
        best = max(summaries, key=lambda s: s.f1_score)
        worst = min(summaries, key=lambda s: s.f1_score)

        return {
            'pairwise_agreement': pairwise,
            'average_agreement': avg_agreement,
            'best_detector': best.detector_name,
            'worst_detector': worst.detector_name,
            'unanimous_files': unanimous,
            'split_files': split,
            'per_file_verdicts': per_file_verdicts,
        }

    def _compute_overall_statistics(self, summaries: List[EvaluationDetectorSummary]) -> Optional[Dict]:
        if not summaries:
            return None

        best_acc = max(summaries, key=lambda s: s.accuracy)
        best_f1 = max(summaries, key=lambda s: s.f1_score)
        best_recall = max(summaries, key=lambda s: s.recall)
        best_prec = max(summaries, key=lambda s: s.precision)
        avg_acc = round(sum(s.accuracy for s in summaries) / len(summaries), 4)

        return {
            'best_accuracy_detector': best_acc.detector_name,
            'best_f1_detector': best_f1.detector_name,
            'best_recall_detector': best_recall.detector_name,
            'best_precision_detector': best_prec.detector_name,
            'avg_accuracy_all_detectors': avg_acc,
        }

    def _compute_frame_level_metrics(self, dataset_file: DatasetFile,
                                     detection_result: dict) -> Optional[Dict]:
        """Compute frame-level precision/recall/F1 against ground truth CSV."""
        if not dataset_file.annotations_path:
            return None

        # Find dataset directory from the file's context
        dataset_dir = None
        for ds_name, manifest in self.dataset_manager._datasets.items():
            if dataset_file in manifest.files:
                dataset_dir = self.dataset_manager.datasets_dir / ds_name
                break

        if dataset_dir is None:
            return None

        ann_path = dataset_dir / dataset_file.annotations_path
        if not ann_path.exists():
            return None

        try:
            gt_frames = set()
            with open(ann_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('fall_detected', '').lower() == 'true':
                        gt_frames.add(int(row['frame_index']))

            det_frames = set()
            for fr in detection_result.get('frame_results', []):
                if fr.get('fall_detected', False):
                    det_frames.add(fr.get('frame_index', -1))

            if not gt_frames and not det_frames:
                return {'precision': 1.0, 'recall': 1.0, 'f1': 1.0, 'temporal_iou': 1.0}

            tp = len(gt_frames & det_frames)
            fp = len(det_frames - gt_frames)
            fn = len(gt_frames - det_frames)

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

            union = len(gt_frames | det_frames)
            temporal_iou = tp / union if union > 0 else 0.0

            return {
                'precision': round(precision, 4),
                'recall': round(recall, 4),
                'f1': round(f1, 4),
                'temporal_iou': round(temporal_iou, 4),
            }

        except Exception:
            return None

    # === Status / Results ===

    def get_evaluation_status(self, eval_id: str) -> Optional[Dict]:
        job = self._evaluations.get(eval_id)
        if not job:
            return None
        return job.get_summary()

    def get_evaluation_results(self, eval_id: str) -> Optional[Dict]:
        job = self._evaluations.get(eval_id)
        if not job:
            return None
        if job.result:
            return job.result.to_dict()
        return job.to_dict()

    def list_evaluations(self) -> List[Dict]:
        return [job.get_summary() for job in self._evaluations.values()]

    def cancel_evaluation(self, eval_id: str) -> Dict:
        job = self._evaluations.get(eval_id)
        if not job:
            return {'error': 'NOT_FOUND', 'message': f'Evaluation "{eval_id}" not found'}
        if job.status not in ('pending', 'running'):
            return {
                'error': 'NOT_CANCELLABLE',
                'message': f'Evaluation is already {job.status} — cannot cancel',
            }
        job.cancelled = True
        return {
            'eval_id': eval_id,
            'message': 'Cancellation requested — job will stop after the current file completes',
        }

    def get_all_detectors_summary(self, detector_names: List[str]) -> List[Dict]:
        """Compact summary for all detectors in one pass — for the /detectors/summary endpoint."""

        # Bootstrap per-detector accumulators
        acc = {
            name: {
                'detector_name': name,
                'total_jobs': 0,
                'successful_jobs': 0,
                'failed_jobs': 0,
                '_job_times': [],
                '_last_seen': None,
                'total_evaluations': 0,
                'total_files_evaluated': 0,
                'overall_accuracy': None,
                'overall_f1': None,
                'tendency': None,
                '_tp': 0, '_tn': 0, '_fp': 0, '_fn': 0,
            }
            for name in detector_names
        }

        # Single pass over orchestrator jobs
        for job in self.orchestrator._jobs.values():
            for det_name, sub in job.sub_tasks.items():
                if det_name not in acc:
                    continue
                a = acc[det_name]
                a['total_jobs'] += 1
                if sub.status == 'completed':
                    a['successful_jobs'] += 1
                    if sub.result and sub.result.get('processing_time_ms'):
                        a['_job_times'].append(sub.result['processing_time_ms'])
                    if sub.completed_at:
                        if a['_last_seen'] is None or sub.completed_at > a['_last_seen']:
                            a['_last_seen'] = sub.completed_at
                elif sub.status == 'failed':
                    a['failed_jobs'] += 1

        # Single pass over evaluations
        for job in self._evaluations.values():
            if not job.result:
                continue
            for summary in job.result.detector_summaries:
                if summary.detector_name not in acc:
                    continue
                a = acc[summary.detector_name]
                a['total_evaluations'] += 1
                a['total_files_evaluated'] += summary.total_files
                a['_tp'] += summary.true_positives
                a['_tn'] += summary.true_negatives
                a['_fp'] += summary.false_positives
                a['_fn'] += summary.false_negatives

        # Finalise each entry
        result = []
        for name in detector_names:
            a = acc[name]
            labeled = a['_tp'] + a['_tn'] + a['_fp'] + a['_fn']
            if labeled > 0:
                tp, tn, fp, fn = a['_tp'], a['_tn'], a['_fp'], a['_fn']
                accuracy = round((tp + tn) / labeled, 4)
                precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0
                a['overall_accuracy'] = accuracy
                a['overall_f1'] = f1
                if fp > 0 and fn == 0:
                    tendency = 'trigger_happy'
                elif fn > 0 and fp == 0:
                    tendency = 'conservative'
                elif fp > fn:
                    tendency = 'leans_false_positive'
                elif fn > fp:
                    tendency = 'leans_false_negative'
                else:
                    tendency = 'balanced'
                a['tendency'] = tendency

            times = a.pop('_job_times')
            a.pop('_tp'); a.pop('_tn'); a.pop('_fp'); a.pop('_fn')
            a['avg_processing_time_ms'] = round(sum(times) / len(times)) if times else None
            a['last_seen'] = a.pop('_last_seen')
            result.append(a)

        return result

    def get_detector_stats(self, detector_name: str) -> Dict:
        """Aggregate stats for a single detector across all evaluations, jobs, and comparisons."""

        # --- Evaluation stats ---
        eval_participations = []
        per_dataset = {}
        total_tp = total_tn = total_fp = total_fn = 0
        all_processing_times = []
        all_confidences_tp = []
        all_confidences_fp = []
        total_fall_frames = 0
        total_frames_processed = 0

        for job in self._evaluations.values():
            if not job.result:
                continue
            for summary in job.result.detector_summaries:
                if summary.detector_name != detector_name:
                    continue

                # Extract detector-specific config (global or per-detector key)
                det_config = None
                if job.config:
                    if detector_name in job.config:
                        det_config = job.config[detector_name]
                    elif not any(k in job.config for k in job.detector_names):
                        det_config = job.config  # global config

                eval_participations.append({
                    'eval_id': job.eval_id,
                    'dataset_name': job.dataset_name,
                    'accuracy': summary.accuracy,
                    'precision': summary.precision,
                    'recall': summary.recall,
                    'f1_score': summary.f1_score,
                    'total_files': summary.total_files,
                    'completed_at': job.completed_at,
                    'detector_config': det_config,
                    'verdict_config': job.verdict_config,
                })

                total_tp += summary.true_positives
                total_tn += summary.true_negatives
                total_fp += summary.false_positives
                total_fn += summary.false_negatives

                for fr in summary.per_file_results:
                    all_processing_times.append(fr.processing_time_ms)
                    total_fall_frames += fr.detector_fall_frame_count
                    total_frames_processed += fr.detector_total_frames
                    if fr.classification == 'TP' and fr.detector_confidence is not None:
                        all_confidences_tp.append(fr.detector_confidence)
                    elif fr.classification == 'FP' and fr.detector_confidence is not None:
                        all_confidences_fp.append(fr.detector_confidence)

                ds = per_dataset.setdefault(job.dataset_name, {
                    'dataset_name': job.dataset_name,
                    'total_files': 0, 'tp': 0, 'tn': 0, 'fp': 0, 'fn': 0,
                })
                ds['total_files'] += summary.total_files
                ds['tp'] += summary.true_positives
                ds['tn'] += summary.true_negatives
                ds['fp'] += summary.false_positives
                ds['fn'] += summary.false_negatives

        # Compute per-dataset accuracy
        for ds in per_dataset.values():
            total = ds['tp'] + ds['tn'] + ds['fp'] + ds['fn']
            ds['accuracy'] = round((ds['tp'] + ds['tn']) / total, 4) if total > 0 else 0

        # Overall eval metrics
        total_eval_files = total_tp + total_tn + total_fp + total_fn
        if total_eval_files > 0:
            raw_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
            raw_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
            raw_f1 = 2 * raw_precision * raw_recall / (raw_precision + raw_recall) if (raw_precision + raw_recall) > 0 else 0
            overall_accuracy = round((total_tp + total_tn) / total_eval_files, 4)
            overall_precision = round(raw_precision, 4)
            overall_recall = round(raw_recall, 4)
            overall_f1 = round(raw_f1, 4)
        else:
            overall_accuracy = overall_precision = overall_recall = overall_f1 = None

        # Tendency
        tendency = None
        if total_fp > 0 and total_fn == 0:
            tendency = 'trigger_happy'
        elif total_fn > 0 and total_fp == 0:
            tendency = 'conservative'
        elif total_fp > total_fn:
            tendency = 'leans_false_positive'
        elif total_fn > total_fp:
            tendency = 'leans_false_negative'
        elif total_eval_files > 0:
            tendency = 'balanced'

        evaluation_stats = {
            'total_evaluations': len(eval_participations),
            'total_files_evaluated': total_eval_files,
            'overall': {
                'accuracy': overall_accuracy,
                'precision': overall_precision,
                'recall': overall_recall,
                'f1_score': overall_f1,
            },
            'tp': total_tp,
            'tn': total_tn,
            'fp': total_fp,
            'fn': total_fn,
            'tendency': tendency,
            'avg_processing_time_ms': round(sum(all_processing_times) / len(all_processing_times)) if all_processing_times else None,
            'avg_confidence_on_tp': round(sum(all_confidences_tp) / len(all_confidences_tp), 4) if all_confidences_tp else None,
            'avg_confidence_on_fp': round(sum(all_confidences_fp) / len(all_confidences_fp), 4) if all_confidences_fp else None,
            'total_fall_frames': total_fall_frames,
            'total_frames_processed': total_frames_processed,
            'avg_fall_frame_percentage': round(total_fall_frames / total_frames_processed, 4) if total_frames_processed > 0 else None,
            'per_dataset': list(per_dataset.values()),
            'evaluations': eval_participations,
        }

        # --- Detection job stats ---
        total_jobs = 0
        successful_jobs = 0
        failed_jobs = 0
        job_times = []

        for job in self.orchestrator._jobs.values():
            for task_key, sub_task in job.sub_tasks.items():
                if sub_task.detector_name != detector_name:
                    continue
                total_jobs += 1
                if sub_task.status == 'completed':
                    successful_jobs += 1
                    if sub_task.result and sub_task.result.get('processing_time_ms'):
                        job_times.append(sub_task.result['processing_time_ms'])
                elif sub_task.status == 'failed':
                    failed_jobs += 1

        detection_stats = {
            'total_jobs': total_jobs,
            'successful': successful_jobs,
            'failed': failed_jobs,
            'avg_processing_time_ms': round(sum(job_times) / len(job_times)) if job_times else None,
        }

        # --- Comparison stats ---
        agreements = {}
        for comp in self.comparison_engine._comparisons.values():
            if detector_name not in comp.detectors:
                continue
            if not comp.comparison_result:
                continue
            matrix = comp.comparison_result.get('agreement_matrix', {}).get('matrix', {})
            row = matrix.get(detector_name, {})
            for other, score in row.items():
                if other == detector_name:
                    continue
                if other not in agreements:
                    agreements[other] = {'total_score': 0, 'count': 0}
                agreements[other]['total_score'] += score
                agreements[other]['count'] += 1

        comparison_stats = {}
        for other, data in agreements.items():
            if data['count'] > 0:
                comparison_stats[other] = round(data['total_score'] / data['count'], 4)

        return {
            'detector_name': detector_name,
            'evaluation_stats': evaluation_stats,
            'detection_stats': detection_stats,
            'comparison_stats': comparison_stats if comparison_stats else None,
        }

    def export_results(self, eval_id: str, fmt: str = 'json') -> Optional[Dict]:
        job = self._evaluations.get(eval_id)
        if not job or not job.result:
            return None

        if fmt == 'json':
            return {
                'format': 'json',
                'data': job.result.to_dict(),
            }

        if fmt == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                'filename', 'ground_truth', 'detector', 'verdict', 'match',
                'classification', 'confidence', 'fall_frames', 'total_frames',
                'processing_time_ms',
            ])

            for summary in job.result.detector_summaries:
                for fr in summary.per_file_results:
                    writer.writerow([
                        fr.filename,
                        fr.ground_truth_label,
                        summary.detector_name,
                        fr.detector_verdict,
                        fr.match,
                        fr.classification,
                        fr.detector_confidence,
                        fr.detector_fall_frame_count,
                        fr.detector_total_frames,
                        fr.processing_time_ms,
                    ])

            return {
                'format': 'csv',
                'data': output.getvalue(),
            }

        return None
