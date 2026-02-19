
import uuid
from typing import Dict, List, Tuple, Set, Optional
from datetime import datetime

from gateway.models import ComparisonJob, ComparisonResult


class ComparisonEngine:

    def __init__(self):
        self._comparisons: Dict[str, ComparisonJob] = {}

    def create_comparison_job(self, job_id: str, detectors: List[str],
                               input_file: str, input_type: str,
                               label: str = None) -> ComparisonJob:
        comparison_id = f'c-{uuid.uuid4()}'
        job = ComparisonJob(
            comparison_id=comparison_id,
            job_id=job_id,
            detectors=detectors,
            input_file=input_file,
            input_type=input_type,
            label=label,
            status='pending'
        )
        self._comparisons[comparison_id] = job
        return job

    def update_job_id(self, comparison_id: str, job_id: str) -> None:
        job = self._comparisons.get(comparison_id)
        if job:
            job.job_id = job_id

    def fail_comparison(self, comparison_id: str, error: str) -> None:
        job = self._comparisons.get(comparison_id)
        if job:
            job.status = 'failed'
            job.completed_at = datetime.utcnow().isoformat()
            job.error = error

    def compare_results(self, comparison_id: str, detector_results: Dict[str, Dict]) -> ComparisonResult:
        job = self._comparisons.get(comparison_id)
        if not job:
            raise ValueError(f'Comparison {comparison_id} not found')

        job.status = 'running'
        job.started_at = datetime.utcnow().isoformat()

        try:
            detector_ranges: Dict[str, List[Tuple[float, float]]] = {}
            detector_summaries: List[Dict] = []

            for detector_name, result in detector_results.items():
                ranges = self._extract_fall_time_ranges(result.get('frame_results', []))
                detector_ranges[detector_name] = ranges

                summary = self._build_detector_summary(detector_name, result, ranges)
                detector_summaries.append(summary)

            agreement_matrix = self._compute_jaccard_matrix(detector_ranges)

            event_comparison = self._extract_events(detector_ranges, tolerance_ms=1000)

            unified_timeline = self._build_unified_timeline(detector_results)

            comparison_notes = self._generate_comparison_notes(
                detector_summaries, agreement_matrix, event_comparison
            )

            detector_capabilities = {
                name: {
                    'multi_person': result.get('meta', {}).get('multi_person', False),
                    'provides_keypoints': self._has_keypoints(result)
                }
                for name, result in detector_results.items()
            }

            comparison_result = ComparisonResult(
                comparison_id=comparison_id,
                job_id=job.job_id,
                detectors=job.detectors,
                input_file=job.input_file,
                status='completed',
                created_at=job.created_at,
                completed_at=datetime.utcnow().isoformat(),
                detector_summaries=detector_summaries,
                agreement_matrix=agreement_matrix,
                event_comparison=event_comparison,
                unified_timeline=unified_timeline,
                comparison_notes=comparison_notes,
                detector_capabilities=detector_capabilities,
                results=detector_results
            )

            job.status = 'completed'
            job.completed_at = datetime.utcnow().isoformat()
            job.comparison_result = comparison_result.to_dict()

            return comparison_result

        except Exception as e:
            job.status = 'failed'
            job.completed_at = datetime.utcnow().isoformat()
            job.error = str(e)
            raise

    def _extract_fall_time_ranges(self, frame_results: List[Dict]) -> List[Tuple[float, float]]:
        if not frame_results:
            return []

        ranges: List[Tuple[float, float]] = []
        in_fall = False
        fall_start_ms = None
        prev_timestamp_ms = None

        for frame in frame_results:
            timestamp_ms = frame.get('timestamp_ms', 0)
            fall_detected = frame.get('fall_detected', False)

            if fall_detected and not in_fall:
                fall_start_ms = timestamp_ms
                in_fall = True
            elif not fall_detected and in_fall:
                if fall_start_ms is not None and prev_timestamp_ms is not None:
                    ranges.append((fall_start_ms, prev_timestamp_ms))
                in_fall = False
                fall_start_ms = None

            prev_timestamp_ms = timestamp_ms

        if in_fall and fall_start_ms is not None and prev_timestamp_ms is not None:
            ranges.append((fall_start_ms, prev_timestamp_ms))

        return ranges

    def _build_detector_summary(self, detector_name: str, result: Dict,
                                  fall_ranges: List[Tuple[float, float]]) -> Dict:
        total_frames = result.get('total_frames', 0)
        fall_frames = result.get('summary', {}).get('fall_frames_count', 0)
        fall_percentage = result.get('summary', {}).get('fall_percentage', 0)
        processing_time_ms = result.get('processing_time_ms', 0)
        category = result.get('meta', {}).get('category', 'unknown')
        multi_person = result.get('meta', {}).get('multi_person', False)

        return {
            'detector': detector_name,
            'category': category,
            'multi_person': multi_person,
            'total_frames': total_frames,
            'fall_frames': fall_frames,
            'fall_percentage': round(fall_percentage, 1),
            'processing_time_ms': processing_time_ms,
            'fall_time_ranges_ms': [[int(start), int(end)] for start, end in fall_ranges]
        }

    def _compute_jaccard_matrix(self, detector_ranges: Dict[str, List[Tuple[float, float]]]) -> Dict:
        detectors = list(detector_ranges.keys())
        matrix = {}

        for det_a in detectors:
            matrix[det_a] = {}
            for det_b in detectors:
                if det_a == det_b:
                    matrix[det_a][det_b] = 1.0
                else:
                    jaccard = self._jaccard_similarity(
                        detector_ranges[det_a],
                        detector_ranges[det_b]
                    )
                    matrix[det_a][det_b] = round(jaccard, 3)

        all_pairs = [
            matrix[det_a][det_b]
            for det_a in detectors
            for det_b in detectors
            if det_a != det_b
        ]
        avg_agreement = round(sum(all_pairs) / len(all_pairs), 3) if all_pairs else 0.0

        return {
            'description': 'Pairwise Jaccard similarity on fall time ranges (0.0 = no overlap, 1.0 = perfect agreement)',
            'matrix': matrix,
            'average_pairwise_agreement': avg_agreement
        }

    def _jaccard_similarity(self, ranges_a: List[Tuple[float, float]],
                             ranges_b: List[Tuple[float, float]]) -> float:
        if not ranges_a and not ranges_b:
            return 1.0
        if not ranges_a or not ranges_b:
            return 0.0

        intersection = self._calculate_time_overlap(ranges_a, ranges_b)

        union = self._calculate_total_time(ranges_a) + self._calculate_total_time(ranges_b) - intersection

        return intersection / union if union > 0 else 0.0

    def _calculate_time_overlap(self, ranges_a: List[Tuple[float, float]],
                                  ranges_b: List[Tuple[float, float]]) -> float:
        total_overlap = 0.0

        for start_a, end_a in ranges_a:
            for start_b, end_b in ranges_b:
                overlap_start = max(start_a, start_b)
                overlap_end = min(end_a, end_b)
                if overlap_start < overlap_end:
                    total_overlap += (overlap_end - overlap_start)

        return total_overlap

    def _calculate_total_time(self, ranges: List[Tuple[float, float]]) -> float:
        if not ranges:
            return 0.0

        merged = self._merge_ranges(ranges)
        return sum(end - start for start, end in merged)

    def _merge_ranges(self, ranges: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        if not ranges:
            return []

        sorted_ranges = sorted(ranges, key=lambda x: x[0])
        merged = [sorted_ranges[0]]

        for start, end in sorted_ranges[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))

        return merged

    def _extract_events(self, detector_ranges: Dict[str, List[Tuple[float, float]]],
                        tolerance_ms: float = 1000) -> Dict:
        all_events: List[Tuple[float, str, Tuple[float, float]]] = []
        for detector_name, ranges in detector_ranges.items():
            for start, end in ranges:
                midpoint = (start + end) / 2
                all_events.append((midpoint, detector_name, (start, end)))

        all_events.sort(key=lambda x: x[0])

        grouped_events: List[Dict] = []
        used_indices: Set[int] = set()

        for i, (midpoint_i, detector_i, range_i) in enumerate(all_events):
            if i in used_indices:
                continue

            event_detectors = {detector_i: range_i}
            used_indices.add(i)

            for j, (midpoint_j, detector_j, range_j) in enumerate(all_events):
                if j in used_indices:
                    continue
                if abs(midpoint_i - midpoint_j) <= tolerance_ms:
                    event_detectors[detector_j] = range_j
                    used_indices.add(j)

            all_detectors = set(detector_ranges.keys())
            detectors_agreeing = list(event_detectors.keys())
            detectors_missing = list(all_detectors - set(detectors_agreeing))
            consensus = len(detectors_agreeing) == len(all_detectors)

            grouped_events.append({
                'event_index': len(grouped_events),
                'approximate_time_ms': int(midpoint_i),
                'detectors_agreeing': detectors_agreeing,
                'detectors_missing': detectors_missing,
                'consensus': consensus
            })

        consensus_count = sum(1 for e in grouped_events if e['consensus'])
        event_agreement_rate = round(consensus_count / len(grouped_events), 3) if grouped_events else 0.0

        return {
            'description': f'Event-level comparison: did detectors find the same fall events? (tolerance: {int(tolerance_ms)}ms)',
            'tolerance_ms': int(tolerance_ms),
            'events': grouped_events,
            'total_unique_events': len(grouped_events),
            'consensus_events': consensus_count,
            'event_agreement_rate': event_agreement_rate
        }

    def _build_unified_timeline(self, detector_results: Dict[str, Dict]) -> Dict:
        frame_data: Dict[int, Dict] = {}

        for detector_name, result in detector_results.items():
            for frame in result.get('frame_results', []):
                timestamp_ms = int(frame.get('timestamp_ms', 0))
                frame_index = frame.get('frame_index', 0)
                fall_detected = frame.get('fall_detected', False)

                if timestamp_ms not in frame_data:
                    frame_data[timestamp_ms] = {
                        'frame_index': frame_index,
                        'timestamp_ms': timestamp_ms,
                        'detectors': {}
                    }

                frame_data[timestamp_ms]['detectors'][detector_name] = fall_detected

        fall_frames = [
            data for data in frame_data.values()
            if any(data['detectors'].values())
        ]

        fall_frames.sort(key=lambda x: x['timestamp_ms'])

        return {
            'description': 'Frame-by-frame view of each detector\'s verdict. Only frames where at least one detector detected a fall are included.',
            'frames': fall_frames
        }

    def _generate_comparison_notes(self, detector_summaries: List[Dict],
                                     agreement_matrix: Dict,
                                     event_comparison: Dict) -> List[str]:
        notes = []

        matrix = agreement_matrix['matrix']
        detectors = list(matrix.keys())

        if len(detectors) >= 2:
            max_agreement = 0.0
            max_pair = None
            for i, det_a in enumerate(detectors):
                for det_b in detectors[i+1:]:
                    agreement = matrix[det_a][det_b]
                    if agreement > max_agreement:
                        max_agreement = agreement
                        max_pair = (det_a, det_b)

            if max_pair and max_agreement > 0.7:
                notes.append(
                    f'{max_pair[0]} and {max_pair[1]} show highest agreement ({max_agreement:.2f}) '
                    f'despite potentially different approaches.'
                )

        events = event_comparison.get('events', [])
        for event in events:
            if not event['consensus']:
                detectors_agreeing = event['detectors_agreeing']
                if len(detectors_agreeing) == 1:
                    detector = detectors_agreeing[0]
                    time_ms = event['approximate_time_ms']
                    notes.append(
                        f'{detector} detected a fall event at ~{time_ms}ms that other detectors missed. '
                        f'This may be a false positive or detection of subtle motion.'
                    )

        avg_agreement = agreement_matrix['average_pairwise_agreement']
        if avg_agreement < 0.5:
            notes.append(
                f'Overall agreement is low ({avg_agreement:.2f}). This indicates significant differences '
                f'in detection strategies or sensitivities.'
            )
        elif avg_agreement > 0.8:
            notes.append(
                f'Overall agreement is high ({avg_agreement:.2f}). Detectors show consistent results '
                f'despite different underlying approaches.'
            )

        return notes

    def _has_keypoints(self, result: Dict) -> bool:
        frame_results = result.get('frame_results', [])
        if not frame_results:
            return False

        for frame in frame_results:
            persons = frame.get('persons', [])
            if persons:
                first_person = persons[0]
                keypoints = first_person.get('keypoints', [])
                return len(keypoints) > 0

        return False

    def get_comparison(self, comparison_id: str) -> Optional[ComparisonJob]:
        return self._comparisons.get(comparison_id)

    def list_comparisons(self) -> List[Dict]:
        return [job.get_summary() for job in self._comparisons.values()]
