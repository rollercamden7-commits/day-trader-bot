"""
Tests for the safety lock.   Run:  python -m unittest discover day_trader/tests
"""
import unittest
from types import SimpleNamespace

from day_trader import safety

PAPER_KEY = {"DT_ALPACA_API_KEY": "PKTESTTESTTEST"}
LIVE_KEY = {"DT_ALPACA_API_KEY": "AKTESTTESTTEST"}


class SafetyLockTests(unittest.TestCase):
    def test_paper_key_starts(self):
        self.assertEqual(safety.check(PAPER_KEY), "paper")

    def test_live_key_refused(self):
        with self.assertRaises(safety.LiveTradingBlocked):
            safety.check(LIVE_KEY)

    def test_live_url_refused(self):
        env = dict(PAPER_KEY, APCA_API_BASE_URL="https://api.alpaca.markets")
        with self.assertRaises(safety.LiveTradingBlocked):
            safety.check(env)

    def test_paper_url_ok(self):
        env = dict(PAPER_KEY, APCA_API_BASE_URL="https://paper-api.alpaca.markets")
        self.assertEqual(safety.check(env), "paper")

    def test_allow_false_still_refuses(self):
        with self.assertRaises(safety.LiveTradingBlocked):
            safety.check(dict(LIVE_KEY, ALLOW_LIVE_TRADING="false"))

    def test_allow_true_permits_live(self):
        self.assertEqual(safety.check(dict(LIVE_KEY, ALLOW_LIVE_TRADING="true")), "live")

    def test_connected_to_live_server_refused(self):
        fake_client = SimpleNamespace(_base_url="https://api.alpaca.markets")
        with self.assertRaises(safety.LiveTradingBlocked):
            safety.verify_connected_paper(fake_client, "paper")

    def test_connected_to_paper_server_ok(self):
        fake_client = SimpleNamespace(_base_url="https://paper-api.alpaca.markets")
        safety.verify_connected_paper(fake_client, "paper")


if __name__ == "__main__":
    unittest.main()
