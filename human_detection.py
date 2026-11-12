"""Person detection on the latest shared frame; never opens another camera.

YOLO API reference: https://github.com/ultralytics/ultralytics
"""
import math
from pathlib import Path
import threading
import time


class PersonDetector:
    def __init__(self, backend='hog', model_path=None, confidence=.5):
        if backend not in ('hog', 'yolo'):
            raise ValueError('Person detector must be hog or yolo')
        if not math.isfinite(confidence) or not 0 < confidence <= 1:
            raise ValueError('Person confidence must be between 0 and 1')
        self.backend, self.confidence = backend, confidence
        if backend == 'yolo':
            if not model_path or not Path(model_path).is_file():
                raise ValueError('YOLO needs a local model file. Download yolo11n.pt first and enter its path.')
            from ultralytics import YOLO
            self.model = YOLO(str(model_path))
            # Find the person class by name instead of assuming custom models use COCO IDs.
            names = self.model.names
            names = names.items() if isinstance(names, dict) else enumerate(names)
            self.person_classes = [int(i) for i, name in names if str(name).lower() == 'person']
            if not self.person_classes:
                raise ValueError('The model must contain a class named person')
        else:
            import cv2
            self.model = cv2.HOGDescriptor()
            self.model.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def detect(self, frame):
        if self.backend == 'yolo':
            result = self.model.predict(source=frame, classes=self.person_classes,
                                        conf=self.confidence, imgsz=320, device='cpu', verbose=False)[0]
            return [{'box': [int(x1), int(y1), int(x2-x1), int(y2-y1)], 'confidence': float(score)}
                    for (x1, y1, x2, y2), score in zip(result.boxes.xyxy.cpu().tolist(),
                                                     result.boxes.conf.cpu().tolist())]
        if frame.shape[0] < 128 or frame.shape[1] < 64:
            raise ValueError('HOG needs frames at least 64 pixels wide and 128 high')
        import cv2
        boxes, weights = self.model.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
        if not len(boxes):
            return []
        # HOG weights are detector margins, not calibrated probabilities.
        scores = [float(w) for w in weights]
        indices = cv2.dnn.NMSBoxes([list(map(int, box)) for box in boxes], scores, 0.0, .4)
        return [{'box': [int(v) for v in boxes[int(i)]], 'confidence': None}
                for i in __import__('numpy').asarray(indices).flatten()]


class PersonWorker:
    """One pending frame; slow inference cannot accumulate a camera backlog."""
    def __init__(self, backend='hog', model_path=None, confidence=.5, factory=PersonDetector):
        self.condition = threading.Condition()
        self.pending = None
        self.closed = False
        self.result = {'detections': [], 'human_updated': None, 'human_error': None}
        self.args = (backend, model_path, confidence)
        self.factory = factory
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, frame):
        with self.condition:
            if not self.closed:
                self.pending = (frame.copy(), time.monotonic())
                self.condition.notify()

    def snapshot(self):
        with self.condition:
            return dict(self.result, detections=list(self.result['detections']))

    def _run(self):
        try:
            detector = self.factory(*self.args)
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.closed or self.pending is not None)
                    if self.closed:
                        return
                    frame, captured = self.pending
                    self.pending = None
                detections = detector.detect(frame)
                with self.condition:
                    self.result.update(detections=detections, human_updated=captured)
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.result.update(human_error=str(exc), human_updated=None, detections=[])
                self.closed = True
                self.pending = None
                self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.pending = None
            self.condition.notify()
        self.thread.join(timeout=2)
