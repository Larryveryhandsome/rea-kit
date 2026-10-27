# -*- coding: utf-8 -*-
"""安裝 pre-commit 守門（CLAUDE.md §2）。clone 完、或發現守門沒擋時跑一次：

    python tools/install_hooks.py

hook 一律跑「正在 commit 的那個 checkout」裡的 tools/pii_scan.py。
不能寫死 git common dir 那份：在 git worktree 裡 commit 時，common dir 指向主 checkout，
那份 pii_scan 會去掃主 checkout 的 staged diff——worktree 的新增行就整批沒被掃到。
"""
import pathlib
import subprocess
import sys

HOOK = """#!/bin/sh
# 去識別化／個資守門（CLAUDE.md §2／§4）。命中就擋；沒有 --no-verify 這條路。
# 由 tools/install_hooks.py 產生；跑的是「目前 checkout」的 pii_scan（worktree 也對）。
top="$(git rev-parse --show-toplevel)" || exit 1
python "$top/tools/pii_scan.py" || exit 1
exit 0
"""


def main():
    # 路徑含中文：一律拿 bytes 自己用 utf-8 解，不靠系統 code page（cp950 會炸）
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True,
                            check=True).stdout.decode("utf-8", "replace").strip()
    hooks = pathlib.Path(common).resolve() / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    dst = hooks / "pre-commit"
    dst.write_text(HOOK, encoding="utf-8", newline="\n")
    try:
        dst.chmod(0o755)
    except OSError:
        pass
    print("✓ pre-commit 已安裝：", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
