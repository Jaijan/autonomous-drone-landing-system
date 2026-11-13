import unittest
from config import Protocol
from ir.blink_decoder import BlinkDecoder, simulate_blink
from vision_service import VisionService
from unittest.mock import patch


class BlinkTests(unittest.TestCase):
    def test_confirmed_half_second_beacon(self):
        service = VisionService()
        with patch.object(service.stop_event, 'wait', return_value=False):
            service._run('simulation', Protocol('RTH', .5), None, signal_protocol='blink')
        self.assertEqual(service.data['validation'], 'validated')
        self.assertEqual(service.data['message'], 'RTH')
        self.assertIn('RTH request received', service.data['request'])
        self.assertFalse(service.data['transmission_enabled'])

    def test_wrong_blink_rate_rejected(self):
        decoder = BlinkDecoder(Protocol('RTH', .5))
        self.assertFalse(any(decoder.feed(*row) for row in simulate_blink(.2)))

    def test_loss_breaks_confirmation_cycle(self):
        decoder = BlinkDecoder(Protocol('RTH', .5))
        rows = list(simulate_blink(.5, cycles=3))
        rows[35] = (rows[35][0], None, 0)
        self.assertFalse(any(decoder.feed(*row) for row in rows))

    def test_sparse_edges_do_not_prove_continuity(self):
        decoder = BlinkDecoder(Protocol('RTH', .5))
        self.assertFalse(any(decoder.feed(n*.5, bool(n%2), 1) for n in range(20)))

    def test_steady_light_rejected(self):
        decoder = BlinkDecoder(Protocol('RTH', .5))
        self.assertFalse(any(decoder.feed(n*.05, True, 1) for n in range(200)))
