"""Run release gates without remote operations. Use an environment with dev deps."""
import json
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def main():
    for command in ([sys.executable, "scripts/build_release.py", "--check"],
                    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]):
        subprocess.run(command, cwd=ROOT, check=True)
    errors = []
    for path in ROOT.rglob("*.md"):
        if any(part in {".git", ".venv", "archive"} for part in path.relative_to(ROOT).parts):
            continue
        # Remove fenced examples before checking local links.
        body = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
        for link in re.findall(r"\]\(([^)]+)\)", body):
            if link.startswith(("https://", "http://", "#")):
                continue
            target = unquote(link.split("#")[0])
            if not (path.parent / target).exists():
                errors.append(f"{path.relative_to(ROOT)}: broken link {link}")
    archive = (ROOT / "archive/prompt-v0.md").read_bytes()
    blob_id = hashlib.sha1(b"blob " + str(len(archive)).encode() + b"\0" + archive).hexdigest()
    if blob_id != "a68a98fc87123d84b2366fb227f94efcdbd3a75e":
        errors.append("Historical v0 archive changed")
    if errors:
        raise SystemExit("\n".join(errors))
    print("LOCAL RELEASE CHECKS PASSED. Grok live smoke test remains an operator gate.")


if __name__ == "__main__":
    main()
