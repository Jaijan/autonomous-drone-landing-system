import sys
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import patch
from ir.ir_camera_receiver import REQUIRED, receive

class CameraContractTests(unittest.TestCase):
    def test_human_camera_uses_no_ir_config_and_releases_camera(self):
        stopped = threading.Event()
        class Camera:
            closed = did_stop = False
            def create_video_configuration(self, **kwargs): return kwargs
            def configure(self, config): self.config = config
            def start(self): pass
            def capture_request(self):
                return SimpleNamespace(make_array=lambda _: 'frame',
                                       get_metadata=lambda: {'SensorTimestamp': 1000000000},
                                       release=lambda: None)
            def stop(self): self.did_stop = True
            def close(self): self.closed = True
        camera = Camera()
        class Factory:
            @staticmethod
            def global_camera_info(): return [{'Model': 'ov5647'}]
            def __new__(cls, index): return camera
        def callback(frame, observation):
            self.assertEqual(frame, 'frame')
            self.assertIsNone(observation['state'])
            stopped.set()
        with patch.dict(sys.modules, {'cv2': SimpleNamespace(), 'picamera2': SimpleNamespace(Picamera2=Factory)}):
            rows = list(receive(None, human_only=True, on_frame=callback, stop_event=stopped, preview=False))
        self.assertEqual(rows, [(1.0, None, 0)])
        self.assertTrue(camera.closed and camera.did_stop)

    def settings(self):
        settings = dict.fromkeys(REQUIRED, 1)
        settings.update(size=[640, 480], off_contrast=1, on_contrast=2)
        return settings

    def test_camera_enumeration_rejects_zero_or_two(self):
        for cameras in ([], [{'Model': 'ov5647'}, {'Model': 'ov5647'}]):
            fake = SimpleNamespace(global_camera_info=lambda: cameras)
            with patch.dict(sys.modules, {'cv2': SimpleNamespace(), 'picamera2': SimpleNamespace(Picamera2=fake)}):
                with self.assertRaises(RuntimeError):
                    next(receive(self.settings()))

    def test_unmeasured_settings_rejected(self):
        settings = self.settings()
        settings['gain'] = None
        with patch.dict(sys.modules, {'cv2': SimpleNamespace(), 'picamera2': SimpleNamespace(Picamera2=None)}):
            with self.assertRaises(ValueError):
                next(receive(settings))

    def test_capture_disconnect_yields_unknown_and_cleans_up(self):
        class Camera:
            camera_controls = dict.fromkeys(('AeEnable', 'ExposureTime', 'AnalogueGain'))
            stopped = closed = False
            def create_video_configuration(self, **kw): return kw
            def configure(self, config): pass
            def set_controls(self, controls): pass
            def start(self): pass
            def capture_request(self): raise OSError('camera disconnected')
            def stop(self): self.stopped = True
            def close(self): self.closed = True
        camera = Camera()
        class Factory:
            @staticmethod
            def global_camera_info(): return [{'Model': 'ov5647'}]
            def __new__(cls, index): return camera
        with patch.dict(sys.modules, {'cv2': SimpleNamespace(destroyAllWindows=lambda: None), 'picamera2': SimpleNamespace(Picamera2=Factory)}):
            source = receive(self.settings())
            self.assertIsNone(next(source)[1])
            with self.assertRaises(OSError):
                next(source)
            self.assertTrue(camera.stopped and camera.closed)
