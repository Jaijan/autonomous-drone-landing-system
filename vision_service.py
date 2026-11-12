"""Shared camera diagnostics for the GCS. No flight commands are sent."""
import copy
from collections import deque
import json
import math
from pathlib import Path
import threading
import time

from config import Protocol
from ir.morse_decoder import MorseDecoder
from ir.signal_validator import SignalValidator
from ir.simulation import simulate
from human_detection import PersonWorker


class VisionService:
    def __init__(self):
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.jpeg = None
        self.reset()

    def reset(self):
        self.data = dict(running=False, source='none', error=None, updated=None,
                         humans=None, human_detector='OpenCV HOG (experimental)',
                         ir_state=None, quality=0, centroid=None, message=None,
                         validation='waiting', confirmations=0, beacon_confirmed=False,
                         landing='BLOCKED: landing geometry unvalidated',
                         transmission_enabled=False, boxes=[], frames=0,
                         human_updated=None, human_error=None)
        self.events = deque(maxlen=100)
        self.jpeg = None

    def event(self, kind, detail):
        with self.lock:
            self.events.appendleft({'time': time.time(), 'kind': kind, 'detail': detail})

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.data)
            result['events'] = list(self.events)
        age = None if result['updated'] is None else time.monotonic() - result['updated']
        result['age_seconds'] = age
        result['fresh'] = bool(result['running'] and age is not None and age < 2)
        human_age = None if result['human_updated'] is None else time.monotonic() - result['human_updated']
        result['human_age_seconds'] = human_age
        result['human_fresh'] = bool(result['fresh'] and human_age is not None and human_age < 2 and not result['human_error'])
        if not result['human_fresh']:
            result.update(humans=None, boxes=[])
            result['landing'] = 'BLOCKED: human detection unavailable or stale'
        if not result['fresh']:
            result.update(humans=None, ir_state=None, quality=0, centroid=None,
                          beacon_confirmed=False, boxes=[])
            result['landing'] = 'BLOCKED: camera observations missing or stale'
        return result

    def start(self, mode, message, unit, camera_config=None, human_backend='hog', model_path=None, confidence=.5):
        if not math.isfinite(unit):
            raise ValueError('Dot duration must be finite')
        protocol = Protocol(message, unit)
        if mode not in ('simulation', 'camera', 'human-camera'):
            raise ValueError('Choose simulation, camera or human-camera')
        if human_backend not in ('hog', 'yolo') or not math.isfinite(confidence) or not 0 < confidence <= 1:
            raise ValueError('Choose hog or yolo and confidence between 0 and 1')
        if model_path:
            model_path = str(Path(model_path).expanduser().resolve())
        if mode != 'simulation' and human_backend == 'yolo' and (not model_path or not Path(model_path).is_file()):
            raise ValueError('Provide a local YOLO model path')
        settings = None
        if mode == 'camera':
            if not camera_config:
                raise ValueError('Provide a measured camera configuration file')
            settings = json.loads(Path(camera_config).expanduser().read_text())
            from ir.ir_camera_receiver import validate_settings
            validate_settings(settings)
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Stop the current session before starting another')
            self.reset()
            self.stop_event.clear()
            self.data.update(running=True, source=mode)
            self.data['human_detector'] = 'YOLO person detector' if human_backend == 'yolo' else 'OpenCV HOG (experimental)'
            self.event('session', f'{mode} session started')
            self.thread = threading.Thread(target=self._run, args=(mode, protocol, settings, human_backend, model_path, confidence), daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        thread = self.thread
        if thread:
            thread.join(timeout=3)
        with self.lock:
            self.data['running'] = bool(thread and thread.is_alive())
            if not self.data['running']:
                self.jpeg = None

    def _run(self, mode, protocol, settings, human_backend='hog', model_path=None, confidence=.5):
        source = None
        people = None
        try:
            decoder, validator = MorseDecoder(protocol), SignalValidator(protocol)
            if mode == 'simulation':
                source = simulate(protocol.message, protocol.unit, protocol.confirmations)
            else:
                import cv2
                from ir.ir_camera_receiver import receive
                people = PersonWorker(human_backend, model_path, confidence)

                def on_frame(frame, observation):
                    # Picamera2 RGB888 arrays use OpenCV's BGR byte ordering.
                    people.submit(frame)
                    human = people.snapshot()
                    stamp = human['human_updated']
                    fresh = stamp is not None and time.monotonic() - stamp < 2 and not human['human_error']
                    boxes = [row['box'] for row in human['detections']] if fresh else []
                    count = len(boxes) if fresh else None
                    display = frame.copy()
                    for x, y, w, h in boxes:
                        cv2.rectangle(display, (int(x), int(y)), (int(x+w), int(y+h)), (0, 180, 255), 2)
                    if observation['centroid']:
                        cv2.circle(display, tuple(int(v) for v in observation['centroid']), 12, (0, 255, 0), 2)
                    ok, encoded = cv2.imencode('.jpg', display)
                    if not ok:
                        raise RuntimeError('Camera preview encoding failed')
                    with self.lock:
                        if self.data['humans'] != count:
                            self.event('human', f'{count} person detection(s)' if count is not None else 'Human detections unavailable')
                        if human['human_error'] and human['human_error'] != self.data['human_error']:
                            self.event('error', human['human_error'])
                        self.jpeg = encoded.tobytes()
                        self.data.update(humans=count, centroid=observation['centroid'],
                                         human_updated=stamp, human_error=human['human_error'],
                                         boxes=[[int(v) for v in box] for box in boxes],
                                         frames=self.data['frames'] + 1)

                source = receive(settings, on_frame=on_frame, stop_event=self.stop_event,
                                 preview=False, human_only=mode == 'human-camera')
            previous = None
            for timestamp, state, quality in source:
                if mode == 'simulation' and previous is not None:
                    if self.stop_event.wait(timestamp - previous):
                        break
                previous = timestamp
                if self.stop_event.is_set():
                    break
                if state is None:
                    validator.disconnect()
                decoded = decoder.feed(timestamp, state, quality)
                with self.lock:
                    self.data.update(updated=time.monotonic(), ir_state=state, quality=quality)
                    if decoded:
                        accepted, reason = validator.accept(*decoded, timestamp)
                        self.data.update(message=decoded[0], validation=reason,
                                         confirmations=validator.count,
                                         beacon_confirmed=accepted or validator.latched)
                        self.event('beacon', f'{decoded[0]}: {reason}')
                    if state is None:
                        self.data['beacon_confirmed'] = False
                    count = self.data['humans']
                    self.data['landing'] = ('BLOCKED: person detected' if count else
                                            'BLOCKED: landing geometry unvalidated')
        except Exception as exc:
            with self.lock:
                self.data.update(error=str(exc), beacon_confirmed=False)
                self.event('error', str(exc))
        finally:
            if people is not None:
                people.close()
            if source is not None and hasattr(source, 'close'):
                source.close()
            with self.lock:
                self.data['running'] = False
                self.jpeg = None
                self.event('session', 'Session stopped')
