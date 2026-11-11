"""Exercise the actual launcher routes without connecting to flight hardware."""
import importlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None


@unittest.skipIf(TestClient is None, 'Install fastapi and httpx for GCS route tests')
class GCSRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'drone-gcs'))
        cls.launcher = importlib.import_module('launcher')
        class Section(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/missing':
                    self.send_response(404)
                else:
                    self.send_response(200)
                self.send_header('Content-Type', 'text/html' if self.path in ('/', '/parameters') else 'application/json')
                self.end_headers()
                self.wfile.write(b'<h1>Section loaded</h1>' if self.path in ('/', '/parameters') else self.path.encode())
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Section)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port_patch = patch.object(cls.launcher, 'CHILD_PORT', cls.server.server_port)
        cls.port_patch.start()
        # No context manager: hardware-opening lifespan intentionally stays inactive.
        cls.client = TestClient(cls.launcher.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.port_patch.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_home_uses_same_origin_and_new_brand(self):
        result = self.client.get('/')
        self.assertEqual(result.status_code, 200)
        self.assertIn('AUTO DRONE GCS', result.text)
        self.assertIn("frame.src='/module/'", result.text)
        self.assertNotIn(':8001', result.text)
        self.assertIn('no-store', result.headers['cache-control'])

    def test_embedded_pages_and_absolute_api_calls(self):
        for path in ('/module/', '/module/parameters', '/parameters'):
            self.assertIn('Section loaded', self.client.get(path).text)
        result = self.client.get('/api/status?probe=1')
        self.assertEqual(result.text, '/api/status?probe=1')
        self.assertEqual(result.headers['content-type'], 'application/json')
        self.assertEqual(self.client.get('/missing').status_code, 404)

    def test_parameter_post_body_forwarded(self):
        result = self.client.post('/api/frame/save', json={'frame_class': 1})
        self.assertEqual(result.json(), {'frame_class': 1})

    def test_vision_routes_not_forwarded(self):
        self.assertIn('Human & IR landing', self.client.get('/vision').text)
        self.assertIn('transmission_enabled', self.client.get('/api/vision/status').json())

    def test_section_switch_returns_relative_url(self):
        with patch.object(self.launcher, 'start_child', return_value={'name': 'frame', 'path': '/'}):
            self.assertEqual(self.client.post('/api/open/frame').json()['url'], '/module/')

    def test_upstream_failure_returns_helpful_error(self):
        with patch.object(self.launcher, 'CHILD_PORT', 0):
            result = self.client.get('/module/')
        self.assertEqual(result.status_code, 502)
        self.assertIn('Select the section again', result.json()['detail'])
