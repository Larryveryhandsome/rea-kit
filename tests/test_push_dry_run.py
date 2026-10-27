"""只模擬不送出：REA_PUSH_DRY_RUN=1 時，主動推播不連 LINE、不耗額度；回覆（reply）不受影響。全合成。"""
import os
import unittest
from unittest import mock

from adapters.line.client import LineClient
from adapters.line.fake_api import FakeLineApi, synthetic_line_id

TO = synthetic_line_id("U", "dry-run-agent")


class PushDryRun(unittest.TestCase):
    def test_dry_run_push_never_touches_network(self):
        with FakeLineApi() as api, mock.patch.dict(os.environ, {"REA_PUSH_DRY_RUN": "1"}):
            c = LineClient("test-token", api_base=api.base_url, min_interval=0)
            self.assertTrue(c.dry_run)
            r = c.push(TO, [{"type": "text", "text": "今日報告"}])
            self.assertTrue(r.ok)
            self.assertEqual(api.pushes, [])                       # 一則都沒送出
            self.assertEqual(len(c.simulated), 1)
            self.assertEqual(c.simulated[0]["to"], TO)

    def test_default_is_real_push(self):
        env = {k: v for k, v in os.environ.items() if k != "REA_PUSH_DRY_RUN"}
        with FakeLineApi() as api, mock.patch.dict(os.environ, env, clear=True):
            c = LineClient("test-token", api_base=api.base_url, min_interval=0)
            self.assertFalse(c.dry_run)
            self.assertTrue(c.push(TO, [{"type": "text", "text": "x"}]).ok)
            self.assertEqual(len(api.pushes), 1)

    def test_reply_still_sent_in_dry_run(self):
        with FakeLineApi() as api, mock.patch.dict(os.environ, {"REA_PUSH_DRY_RUN": "1"}):
            c = LineClient("test-token", api_base=api.base_url, min_interval=0)
            self.assertTrue(c.reply("rt1", [{"type": "text", "text": "hi"}]).ok)
            self.assertEqual(len(api.replies), 1)

    def test_bad_recipient_still_rejected_in_dry_run(self):
        with mock.patch.dict(os.environ, {"REA_PUSH_DRY_RUN": "1"}):
            c = LineClient("test-token", api_base="http://127.0.0.1:9", min_interval=0)
            self.assertFalse(c.push("not-an-id", [{"type": "text", "text": "x"}]).ok)


if __name__ == "__main__":
    unittest.main()
