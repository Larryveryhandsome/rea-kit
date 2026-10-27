# -*- coding: utf-8 -*-
"""LINE webhook 簽章：HMAC-SHA256(channel secret, 原始 body) 的 base64，放在 X-Line-Signature。

和舊做法的差別（刻意的）：
  - 沒設 secret 或沒帶簽章＝一律不過（舊做法是「有 secret 才驗」，等於設定漏了就門戶大開）
  - 比對用 hmac.compare_digest（常數時間），不用 ==
"""
from __future__ import annotations

import base64
import hashlib
import hmac


def sign(channel_secret: str, body: bytes) -> str:
    mac = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("ascii")


def verify(channel_secret: str, body: bytes, signature: str) -> bool:
    if not channel_secret or not signature:
        return False
    return hmac.compare_digest(sign(channel_secret, body), signature.strip())
