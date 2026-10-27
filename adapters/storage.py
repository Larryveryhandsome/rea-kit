# -*- coding: utf-8 -*-
"""每租戶資料夾：邏輯隔離＋原子寫檔＋跨行程鎖。

所有轉接器（line、csv…）的落檔都走這裡，所以「租戶 A 讀到租戶 B」只可能壞在一個地方。
資料根目錄＝環境變數 REA_DATA_DIR，沒設就用 repo 下的 data/（已在 .gitignore）。
正式上線換成資料庫時，換掉這一支即可；呼叫端只認 read_json／write_json／append_jsonl／lock。

匯出與刪除整個租戶（個資法：受委託處理者要做得到）也在這裡：export_tenant／delete_tenant。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import time
import zipfile
from typing import Any, Iterator

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA_ENV = "REA_DATA_DIR"

# 租戶 id 會變成資料夾名：只收小寫英數、底線、連字號，擋掉 ../ 與磁碟代號
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
_PART_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,120}$")


RESERVED_PREFIX = "sys-"      # 系統自己用的分區（例：共用通知帳號的帳本與綁定表）；註冊流程不可發給租戶


def validate_tenant_id(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not _TENANT_RE.match(tenant_id):
        raise ValueError("tenant_id 只能是 2–40 字的小寫英數、底線、連字號")
    return tenant_id


def is_reserved_tenant(tenant_id: str) -> bool:
    return str(tenant_id).startswith(RESERVED_PREFIX)


def _validate_parts(parts: tuple[str, ...]) -> None:
    for p in parts:
        if not _PART_RE.match(p) or p in (".", ".."):
            raise ValueError(f"不合法的路徑片段：{p!r}")


class TenantStore:
    def __init__(self, root: str | os.PathLike | None = None):
        self.root = pathlib.Path(root or os.environ.get(DATA_ENV) or (REPO / "data")).resolve()

    # ── 路徑 ──
    def tenant_dir(self, tenant_id: str) -> pathlib.Path:
        return self.root / "tenants" / validate_tenant_id(tenant_id)

    def path(self, tenant_id: str, *parts: str) -> pathlib.Path:
        _validate_parts(parts)
        p = self.tenant_dir(tenant_id).joinpath(*parts)
        # 雙保險：解析後一定還在該租戶資料夾底下
        if self.tenant_dir(tenant_id) not in p.resolve().parents and p.resolve() != self.tenant_dir(tenant_id):
            raise ValueError("路徑跑出租戶資料夾")
        return p

    # ── 讀寫 ──
    def read_json(self, tenant_id: str, *parts: str, default: Any = None) -> Any:
        p = self.path(tenant_id, *parts)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except json.JSONDecodeError as exc:
            # 壞檔不能當成「空的」默默蓋掉——那會把租戶資料清空
            raise ValueError(f"{p.name} 不是合法 JSON，請先修復或從備份還原") from exc

    def write_json(self, tenant_id: str, *parts: str, data: Any) -> None:
        p = self.path(tenant_id, *parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        for attempt in range(20):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                # Windows：別的行程剛好開著目標檔，稍等再換
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, p)

    def append_jsonl(self, tenant_id: str, *parts: str, record: dict) -> None:
        p = self.path(tenant_id, *parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_jsonl(self, tenant_id: str, *parts: str) -> list[dict]:
        p = self.path(tenant_id, *parts)
        out: list[dict] = []
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return out
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue          # 半行（寫到一半斷電）跳過，不讓整檔讀不出來
        return out

    @contextlib.contextmanager
    def lock(self, tenant_id: str, name: str, timeout: float = 15.0) -> Iterator[None]:
        """同一租戶同一資源的跨行程互斥（webhook 執行緒、排程、後台同時寫帳本時用）。"""
        with file_lock(self.path(tenant_id, "_locks", name + ".lock"), timeout=timeout):
            yield

    # ── 個資法：匯出／刪除整個租戶 ──
    def export_tenant(self, tenant_id: str) -> bytes:
        base = self.tenant_dir(tenant_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            if base.exists():
                for f in sorted(base.rglob("*")):
                    if f.is_file() and "_locks" not in f.parts:
                        z.write(f, f.relative_to(base).as_posix())
        return buf.getvalue()

    def delete_tenant(self, tenant_id: str) -> bool:
        base = self.tenant_dir(tenant_id)
        if not base.exists():
            return False
        shutil.rmtree(base)
        return True


@contextlib.contextmanager
def file_lock(path: pathlib.Path, timeout: float = 15.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"等不到鎖：{path.name}")
                time.sleep(0.02)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()
