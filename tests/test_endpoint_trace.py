"""Reject attractive but unsafe text-inactivity endpoint assumptions."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('trace_audit', Path(__file__).resolve().parents[1] /
                                           'device/endpoint_probe/audit_turn_trace.py')
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def rows(*pairs):
    return [{'arrival_ms': t, 'text': s} for t, s in pairs]


class TraceAuditTest(unittest.TestCase):
    def test_no_result_cannot_start_timer(self):
        self.assertIsNone(trace.stable_candidate(rows((100, '')), 20000))

    def test_duplicate_does_not_keep_timer_alive(self):
        self.assertEqual(trace.stable_candidate(rows((500, '为什么'), (2000, '为什么')), 4000),
                         {'at_ms': 2500, 'text_at_candidate': '为什么'})

    def test_correction_even_shorter_is_progress(self):
        self.assertEqual(trace.stable_candidate(rows((500, '为什么月亮'), (1800, '月亮')), 5000)['at_ms'], 3800)

    def test_pause_or_delayed_asr_can_end_before_continuation(self):
        result = trace.stable_candidate(rows((500, '为什么月亮'), (3600, '为什么月亮白天能看见')), 8000)
        self.assertEqual(result, {'at_ms': 2500, 'text_at_candidate': '为什么月亮'})

    def test_update_at_boundary_wins(self):
        self.assertEqual(trace.stable_candidate(rows((500, '火车'), (2500, '火车的车轮')), 5000)['at_ms'], 4500)

    def test_no_extrapolation_after_capture_stops(self):
        self.assertIsNone(trace.stable_candidate(rows((500, '苹果')), 2400))

    def test_empty_update_does_not_extend_timer(self):
        self.assertEqual(trace.stable_candidate(rows((500, '苹果'), (1500, '')), 4000)['at_ms'], 2500)

    def test_out_of_order_arrivals_are_rejected(self):
        with self.assertRaises(ValueError):
            trace.stable_candidate(rows((500, '苹果'), (100, '苹果的')), 4000)

    def test_midnight_is_not_a_negative_duration(self):
        first = trace.stamp('Sep 18 23:59:59.500 x', 2026)
        next_day = trace.stamp('Sep 19 00:00:00.500 x', 2026)
        self.assertEqual((next_day-first).total_seconds(), 1)
