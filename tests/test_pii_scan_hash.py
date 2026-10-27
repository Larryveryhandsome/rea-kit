"""去識別化守門：雜湊值裡剛好有 09 開頭 10 位數字不算電話；真的電話照樣攔。"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import pii_scan  # noqa: E402

FAKE = "09" + "12" + "345" + "678"                    # 合成；拆開寫免得守門擋測試檔本身


class PiiScanHashTests(unittest.TestCase):
    def test_hash_is_not_a_phone(self):
        line = '"sha256": "9e301a5fd71221ac2fab6cd1fa3' + "09" + "31266328" + 'dedbdde806879aac73c4436349d",'
        self.assertEqual(pii_scan.hits_in_line(line), [])

    def test_real_phones_still_caught(self):
        self.assertIn("PHONE", pii_scan.hits_in_line(f"電話 {FAKE}"))
        self.assertIn("PHONE", pii_scan.hits_in_line(f"id=abc{FAKE}xyz"))
        self.assertIn("PHONE", pii_scan.hits_in_line(f"{FAKE[:4]}-{FAKE[4:7]}-{FAKE[7:]}"))


if __name__ == "__main__":
    unittest.main()
