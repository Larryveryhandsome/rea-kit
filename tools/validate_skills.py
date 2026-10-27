"""Validate the public Skill contract without requiring third-party packages."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
REQUIRED = (
    "## SOP",
    "## Decision points",
    "## Checklist",
    "## Template",
    "## Output requirements",
    "## Test cases",
    "## Acceptance criteria",
)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    errors: list[str] = []
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"manifest: {exc}")
        manifest = {}
    for key in ("name", "version", "description", "skills", "interface"):
        if not manifest.get(key):
            errors.append(f"manifest missing {key}")
    if manifest.get("name") != "rea-kit":
        errors.append("manifest name mismatch")
    skill_files = sorted(SKILLS.glob("*/SKILL.md"))
    # 技能數上限 40
    if not 3 <= len(skill_files) <= 40:
        errors.append(f"expected 3-40 product skills, found {len(skill_files)}")
    names: set[str] = set()
    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n") or "\n---\n" not in text:
            errors.append(f"{path}: missing frontmatter")
        else:
            front = text.split("\n---\n", 1)[0]
            name = re.search(r"^name:\s*(\S+)", front, re.M)
            desc = re.search(r"^description:\s*.+", front, re.M)
            if not name or not desc:
                errors.append(f"{path}: frontmatter needs name and description")
            elif name.group(1) in names:
                errors.append(f"duplicate skill name {name.group(1)}")
            elif name:
                names.add(name.group(1))
        for heading in REQUIRED:
            if heading not in text:
                errors.append(f"{path}: missing {heading}")
    if errors:
        print("✗ skill validation failed")
        print("\n".join(f"- {e}" for e in errors))
        return 1
    print(f"✓ skill validation passed ({len(skill_files)} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
