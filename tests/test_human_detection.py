import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from human_detection import PersonDetector, PersonWorker
from vision_service import VisionService
import time


class HumanDetectionTests(unittest.TestCase):
    def test_yolo_person_filter_and_coordinates(self):
        class Values:
            def __init__(self, rows): self.rows = rows
            def cpu(self): return self
            def tolist(self): return self.rows
        class Model:
            names = {0: 'car', 2: 'person'}
            def predict(self, **kwargs):
                self.kwargs = kwargs
                return [SimpleNamespace(boxes=SimpleNamespace(
                    xyxy=Values([[10, 20, 40, 80]]), conf=Values([.9])))]
        model = Model()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.pt'
            path.touch()
            with patch.dict(sys.modules, {'ultralytics': SimpleNamespace(YOLO=lambda _: model)}):
                detector = PersonDetector('yolo', path, .6)
                result = detector.detect('frame')
        self.assertEqual(model.kwargs['classes'], [2])
        self.assertEqual(model.kwargs['conf'], .6)
        self.assertEqual(result, [{'box': [10, 20, 30, 60], 'confidence': .9}])

    def test_worker_replaces_pending_frame_without_blocking_capture(self):
        entered, release = threading.Event(), threading.Event()
        class Frame:
            def __init__(self, number): self.number = number
            def copy(self): return Frame(self.number)
        class Detector:
            def detect(self, frame):
                if frame.number == 1:
                    entered.set()
                    release.wait(3)
                return [{'box': [frame.number, 0, 10, 10], 'confidence': .8}]
        worker = PersonWorker(factory=lambda *args: Detector())
        try:
            worker.submit(Frame(1))
            self.assertTrue(entered.wait(2))
            worker.submit(Frame(2))
            worker.submit(Frame(3))
            with worker.condition:
                self.assertEqual(worker.pending[0].number, 3)
            release.set()
            with worker.condition:
                self.assertTrue(worker.condition.wait_for(
                    lambda: bool(worker.result['detections']) and worker.result['detections'][0]['box'][0] == 3, timeout=3))
        finally:
            release.set()
            worker.close()
        self.assertFalse(worker.thread.is_alive())

    def test_model_error_visible_as_unknown(self):
        def fail(*args): raise RuntimeError('model load failed')
        worker = PersonWorker(factory=fail)
        try:
            with worker.condition:
                self.assertTrue(worker.condition.wait_for(lambda: worker.closed, timeout=2))
            self.assertEqual(worker.snapshot()['human_error'], 'model load failed')
            self.assertIsNone(worker.snapshot()['human_updated'])
        finally:
            worker.close()

    def test_human_results_expire_while_ir_remains_fresh(self):
        service = VisionService()
        service.data.update(running=True, updated=time.monotonic(),
                            humans=0, human_updated=time.monotonic()-3, boxes=[[1, 2, 3, 4]])
        status = service.snapshot()
        self.assertTrue(status['fresh'])
        self.assertFalse(status['human_fresh'])
        self.assertIsNone(status['humans'])
        self.assertEqual(status['boxes'], [])
        self.assertIn('human detection', status['landing'])

    def test_event_history_bounded_and_newest_first(self):
        service = VisionService()
        for number in range(120): service.event('test', str(number))
        events = service.snapshot()['events']
        self.assertEqual(len(events), 100)
        self.assertEqual(events[0]['detail'], '119')
