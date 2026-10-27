"""綁定管理員：串接精靈產生 6 碼，負責人在 LINE 傳「管理員 123456」→ 這個 LINE 帳號就成為管理員。

管理員可以從 LINE 拿管理員面板的登入連結（/admin），也會收到系統通知。
碼 10 分鐘失效、用過即丟；連續輸錯 5 次就作廢，要回精靈重新產生。
"""
from __future__ import annotations

import datetime
import json
import re
import secrets

from adapters.settings_store import SettingsStore

CLAIM_RE = re.compile(r"^管理員\s*(\d{6})$")
TTL = datetime.timedelta(minutes=10)


def _path(settings: SettingsStore):
    return settings.path.with_name("admin_claim.json")


def issue_code(settings: SettingsStore, now=datetime.datetime.now) -> str:
    code = f"{secrets.randbelow(10 ** 6):06d}"
    p = _path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"code": code, "exp": (now() + TTL).isoformat(timespec="seconds"), "fails": 0}),
                 encoding="utf-8")
    return code


def _load(settings):
    try:
        return json.loads(_path(settings).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def redeem(settings: SettingsStore, user_id: str, code: str, now=datetime.datetime.now) -> tuple[bool, str]:
    rec = _load(settings)
    if not rec or rec.get("exp", "") < now().isoformat():
        return False, "這組管理員碼已經失效，請回串接精靈重新產生。"
    if not secrets.compare_digest(str(rec.get("code")), code):
        rec["fails"] = int(rec.get("fails", 0)) + 1
        if rec["fails"] >= 5:
            _path(settings).unlink(missing_ok=True)
            return False, "輸錯太多次，這組碼作廢了，請回串接精靈重新產生。"
        _path(settings).write_text(json.dumps(rec), encoding="utf-8")
        return False, "管理員碼不對，請再看一次精靈畫面上的 6 碼。"
    if not (user_id.startswith("U") and len(user_id) == 33):
        return False, "請在和官方帳號的一對一聊天裡傳。"
    admins = [u for u in settings.get("REA_ADMIN_USERS").split(",") if u.strip()]
    if user_id not in admins:
        admins.append(user_id)
    settings.save({"REA_ADMIN_USERS": ",".join(admins)})
    _path(settings).unlink(missing_ok=True)
    return True, "✓ 你已經是這個系統的管理員了。回到電腦上的串接精靈，畫面會自動打勾。"


def claimed(settings: SettingsStore) -> bool:
    return bool(settings.get("REA_ADMIN_USERS")) and _load(settings) is None


def make_admin_claim_handler(store, settings: SettingsStore | None = None):
    def handler(ctx):
        m = CLAIM_RE.match(ctx.text or "")
        if not m or (ctx.event.get("source") or {}).get("type") != "user":
            return
        ok, msg = redeem(settings or SettingsStore(store.root), ctx.user_id, m.group(1))
        ctx.reply_text(msg)
    return handler
