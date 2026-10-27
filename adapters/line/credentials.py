# -*- coding: utf-8 -*-
"""每租戶的 LINE 官方帳號設定。

一個租戶＝一個人＝一個自己申請的 LINE 官方帳號（CLAUDE.md §5）。金鑰絕不寫進程式或 repo：
  - 測試／單元測試：MemoryCredentialStore
  - 開發機／封測：FileCredentialStore 讀 <資料根>/tenants/<租戶>/line/config.json，
    值可以寫成 "env:變數名" 指向環境變數，真值不落檔
  - 正式上線：換成資料庫（欄位加密），介面不變
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Protocol

from adapters.storage import TenantStore, validate_tenant_id

LINE_ID_RE = re.compile(r"^[CRU][0-9a-f]{32}$")   # U＝個人、C＝群組、R＝多人聊天室


def is_line_id(value: str) -> bool:
    return bool(value) and bool(LINE_ID_RE.match(value))


@dataclass(frozen=True)
class TenantLineConfig:
    tenant_id: str
    channel_secret: str = field(repr=False)
    channel_access_token: str = field(repr=False)
    owner_user_id: str = ""        # 租戶本人：急事通知、審核卡的收件人，也是唯一能按「送出」的人
    review_target: str = ""        # 審核卡送哪；空白＝送 owner_user_id
    extra_reviewers: tuple[str, ...] = ()   # 團隊版才會用：也能按審核鈕的人

    @property
    def review_to(self) -> str:
        return self.review_target or self.owner_user_id

    def can_review(self, user_id: str) -> bool:
        return bool(user_id) and (user_id == self.owner_user_id or user_id in self.extra_reviewers)

    def control_targets(self) -> set[str]:
        """租戶自己下決定的通道（本人私訊、審核群）：推播閘不能攔住它們。"""
        return {x for x in (self.owner_user_id, self.review_target) if x}


class CredentialStore(Protocol):
    def get(self, tenant_id: str) -> TenantLineConfig | None: ...


class MemoryCredentialStore:
    def __init__(self, configs: list[TenantLineConfig] | None = None):
        self._by_id = {c.tenant_id: c for c in (configs or [])}

    def put(self, config: TenantLineConfig) -> None:
        validate_tenant_id(config.tenant_id)
        self._by_id[config.tenant_id] = config

    def get(self, tenant_id: str) -> TenantLineConfig | None:
        return self._by_id.get(tenant_id)


def _resolve(value: str) -> str:
    value = str(value or "")
    if value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value


class FileCredentialStore:
    def __init__(self, store: TenantStore):
        self.store = store

    def get(self, tenant_id: str) -> TenantLineConfig | None:
        try:
            raw = self.store.read_json(tenant_id, "line", "config.json")
        except ValueError:
            return None
        if not raw:
            return None
        secret = _resolve(raw.get("channel_secret"))
        token = _resolve(raw.get("channel_access_token"))
        if not secret or not token:
            return None          # 金鑰不齊＝當作沒設定，webhook 一律擋（不能「沒 secret 就不驗」）
        return TenantLineConfig(
            tenant_id=tenant_id, channel_secret=secret, channel_access_token=token,
            owner_user_id=raw.get("owner_user_id", ""), review_target=raw.get("review_target", ""),
            extra_reviewers=tuple(raw.get("extra_reviewers") or ()))

    def put(self, tenant_id: str, *, channel_secret: str, channel_access_token: str,
            owner_user_id: str = "", review_target: str = "") -> None:
        """後台設定精靈用。建議傳 "env:XXX"；傳真值也行，但檔案就要當金鑰保管。"""
        for uid in (owner_user_id, review_target):
            if uid and not is_line_id(uid):
                raise ValueError("owner_user_id／review_target 必須是 LINE 的 U／C／R 開頭 ID")
        self.store.write_json(tenant_id, "line", "config.json", data={
            "channel_secret": channel_secret, "channel_access_token": channel_access_token,
            "owner_user_id": owner_user_id, "review_target": review_target})
