# -*- coding: utf-8 -*-
"""房仲自動化神器 — 去識別化／個資守門（CLAUDE.md §2／§4）

用法：
    python tools/pii_scan.py            只掃 git staged diff 的新增行（pre-commit 用）
    python tools/pii_scan.py --all      掃整個 repo（commit 前自檢、CI 用）
    python tools/pii_scan.py --path X   掃指定檔／資料夾

擋什麼：
  ① LINE 群／人 ID（C 或 U 開頭 32 碼 hex）
  ② 台灣手機 09xxxxxxxx（排除 UUID／座標誤判；tools/identifiers.txt 的 [public_phones] 白名單除外）
  ③ 身分證字號樣式（1 英文＋9 數字）
  ④ 本機識別字清單 tools/identifiers.txt（品牌、人名、店碼、帳號、埠、第三方系統網域…）
  ⑤ 真值金鑰樣式（LINE channel token 長字串、sk-…、Bearer …）
通過＝exit 0；命中＝列出 檔:行:類別 並 exit 1。沒有 --no-verify 這條路，命中就改到不命中。
"""
import pathlib, re, subprocess, sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _identifiers_file():
    """識別字清單不入版控，所以 git worktree 裡沒有這個檔——找不到就退回主 checkout 那份。
    順序：本 checkout → 環境變數 REA_IDENTIFIERS → git common dir 旁的主 checkout。"""
    import os
    cands = [ROOT / "tools" / "identifiers.txt"]
    if os.environ.get("REA_IDENTIFIERS"):
        cands.append(pathlib.Path(os.environ["REA_IDENTIFIERS"]))
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True,
                                cwd=ROOT).stdout.decode("utf-8", "replace").strip()
        if common:
            cands.append((ROOT / common).resolve().parent / "tools" / "identifiers.txt")
    except Exception:
        pass
    for c in cands:
        if c.exists():
            return c
    return None


IDF = _identifiers_file()
TEXT = (".py", ".ts", ".js", ".tsx", ".jsx", ".md", ".json", ".jsonl", ".csv", ".txt", ".html", ".yaml", ".yml", ".toml", ".env", ".example", ".ps1", ".bat", ".sql")
SKIP = {".git", "node_modules", ".venv", "__pycache__", "dist", ".next"}

LINEID = re.compile(r"(?<![0-9a-zA-Z])[CU][0-9a-f]{32}(?![0-9a-zA-Z])")
PHONE = re.compile(r"09\d{2}[-\s]?\d{3}[-\s]?\d{3}")
UUIDISH = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-|[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
COORD = re.compile(r"\d+\.\d{6,}")
TWID = re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?![0-9])")
SECRET = re.compile(r"(sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9+/=_-]{30,}|[A-Za-z0-9+/=]{150,})")


def load_identifiers():
    words, public = [], set()
    sec = None
    if IDF is None:
        # CI／公開 clone 本來就沒有這份清單；開發機上缺了就等於守門少一層，要講出來
        print("⚠ 找不到 tools/identifiers.txt：本次只掃通用樣式（LINE ID／電話／身分證／金鑰），"
              "不含本機識別字", file=sys.stderr)
    else:
        for ln in IDF.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("[") and s.endswith("]"):
                sec = s[1:-1]; continue
            if sec == "public_phones":
                public.add(re.sub(r"\D", "", s))
            else:
                words.append(s)
    return words, public


WORDS, PUBLIC = load_identifiers()


def _inside_hash(line, start, end):
    """命中位置在 32 字以上連續十六進位字串（雜湊值）裡 → 不是電話。"""
    hexd = set("0123456789abcdefABCDEF")
    if not all(c in hexd for c in line[start:end]):
        return False
    lo, hi = start, end
    while lo > 0 and line[lo - 1] in hexd:
        lo -= 1
    while hi < len(line) and line[hi] in hexd:
        hi += 1
    return hi - lo >= 32


def hits_in_line(line):
    out = []
    if LINEID.search(line):
        out.append("LINE_ID")
    for m in PHONE.finditer(line):
        ctx = line[max(0, m.start() - 40):m.end() + 40]
        if UUIDISH.search(ctx) or COORD.search(ctx):
            continue
        if _inside_hash(line, m.start(), m.end()):         # sha256 之類的雜湊剛好含 09 開頭的 10 位數字
            continue
        if re.sub(r"\D", "", m.group()) in PUBLIC:
            continue
        out.append("PHONE"); break
    if TWID.search(line):
        out.append("TW_ID")
    if SECRET.search(line) and "example" not in line.lower():
        out.append("SECRET")
    for w in WORDS:
        if w in line:
            out.append(f"IDENT:{w}"); break
    return out


def scan_text(path, text, only_added=None):
    bad = []
    lines = text.splitlines()
    for i, ln in enumerate(lines, 1):
        if only_added is not None and i not in only_added:
            continue
        if "pii_scan:allow" in ln:
            continue
        for h in hits_in_line(ln):
            bad.append((str(path), i, h, ln.strip()[:90]))
    return bad


def staged():
    diff = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--cached", "-U0", "--diff-filter=ACMR"],
                          capture_output=True, cwd=ROOT).stdout.decode("utf-8", "replace")
    bad, cur, lineno = [], None, 0
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]; continue
        if ln.startswith("@@"):
            m = re.search(r"\+(\d+)", ln); lineno = int(m.group(1)) - 1 if m else 0; continue
        if ln.startswith("+") and not ln.startswith("+++"):
            lineno += 1
            if cur and cur.endswith(TEXT) and "pii_scan:allow" not in ln:
                for h in hits_in_line(ln[1:]):
                    bad.append((cur, lineno, h, ln[1:].strip()[:90]))
        elif not ln.startswith("-"):
            lineno += 1
    return bad


def _tracked_or_untracked_not_ignored():
    """--all 只掃「會進 repo 的檔」：git 追蹤中＋未追蹤但沒被 .gitignore 排除的。被 ignore 的本機私有檔（識別字清單、docs/_*.md）不掃。"""
    try:
        out = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             capture_output=True, cwd=ROOT).stdout.decode("utf-8", "replace")
        return {ROOT / f for f in out.split(chr(0)) if f}
    except Exception:
        return None


def walk(base):
    allowed = _tracked_or_untracked_not_ignored() if pathlib.Path(base).resolve() == ROOT else None
    for p in sorted(pathlib.Path(base).rglob("*")):
        if any(s in p.parts for s in SKIP) or not p.is_file():
            continue
        if allowed is not None and p.resolve() not in {a.resolve() for a in allowed}:
            continue
        if p.name in ("identifiers.txt", "pii_scan.py"):
            continue
        if p.suffix.lower() in TEXT or p.name.startswith(".env"):
            try:
                yield p, p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main():
    a = sys.argv[1:]
    if "--all" in a:
        bad = [b for p, t in walk(ROOT) for b in scan_text(p.relative_to(ROOT), t)]
    elif "--path" in a:
        tgt = pathlib.Path(a[a.index("--path") + 1])
        bad = [b for p, t in walk(tgt) for b in scan_text(p, t)] if tgt.is_dir() else scan_text(tgt, tgt.read_text(encoding="utf-8", errors="replace"))
    else:
        bad = staged()
    if bad:
        print(f"✗ 去識別化守門命中 {len(bad)} 處（CLAUDE.md §2）：")
        for f, i, h, s in bad[:60]:
            print(f"  {f}:{i} [{h}] {s}")
        if len(bad) > 60:
            print(f"  …另 {len(bad) - 60} 處")
        sys.exit(1)
    print("✓ pii_scan 通過")


if __name__ == "__main__":
    main()
