"""Install self-contained skill: python scripts/install.py /absolute/skills/directory

Copies the canonical skill, agents, and resources into <directory>/geo-audit.
Existing files are retained in a timestamped .backups directory.
"""
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

def install(destination):
    repo = Path(__file__).resolve().parent.parent
    destination = Path(destination).expanduser().resolve() / "geo-audit"
    source = repo / ".claude" / "skills" / "geo-audit"
    if destination == source or repo in destination.parents:
        raise ValueError("Install outside the source repository")
    if destination.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = destination / ".backups" / stamp
        shutil.copytree(destination, backup, ignore=shutil.ignore_patterns(".backups", "__pycache__"))
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "SKILL.md", destination / "SKILL.md")
    shutil.copytree(repo / ".claude" / "agents", destination / "agents", dirs_exist_ok=True)
    shutil.copytree(repo / "scripts", destination / "scripts", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    print(destination)

if __name__ == "__main__":
    install(sys.argv[1])
