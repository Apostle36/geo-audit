"""Stage a complete skill package and atomically activate it, retaining backups.

Repository and installed-bundle layouts are supported. Atomic upgrades require
Linux renameat2; unsupported systems fail without touching the active install.
Global agent definitions are diagnosed, never overwritten. The newest backups
are kept (five by default); older ones are dropped from the new package.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

KEEP_BACKUPS = 5


def exchange(a, b):
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, "renameat2", None)
    if rename is None:
        raise OSError("Atomic directory exchange is unavailable; prior install is unchanged")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(a), -100, os.fsencode(b), 2) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def install(directory, *, source_root=None, keep_backups=KEEP_BACKUPS):
    if keep_backups < 1:
        raise ValueError("Keep at least one backup")
    root = Path(source_root or Path(__file__).resolve().parent.parent).resolve()
    parent = Path(directory).expanduser().resolve()
    destination = parent / "geo-audit"
    if destination == root or root in destination.parents or destination in root.parents:
        raise ValueError("Install outside the source package/repository")
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise ValueError("Destination must be a real directory, not a file or symlink")
    canonical = root / ".claude/skills/geo-audit/SKILL.md"
    skill = canonical if canonical.exists() else root / "SKILL.md"
    agents = root / ".claude/agents" if canonical.exists() else root / "agents"
    required = [skill, root / "scripts/evidence.py", root / "scripts/score.py", root / "scripts/run_contract.py",
                root / "scripts/safe_io.py", root / "scripts/geo-audit-pdf.py", root / "scripts/install.py",
                root / "scripts/requirements.txt", root / "scripts/rubrics/1.2.0.json", root / "docs/RUN-FORMAT.md",
                root / 'scripts/client_report.py', root / 'scripts/review_topics.py', root / 'scripts/version.py',
                root / 'scripts/collect.py', root / 'scripts/new_run.py',
                root / 'docs/AUDIT-DEPTH.md', root / 'docs/CLIENT-REPORT.md']
    roles = ["geo-ai-visibility", "brand-radar", "geo-technical", "geo-content", "geo-schema", "geo-platform-analysis"]
    required += [agents / f"{role}.md" for role in roles]
    for path in required:
        if not path.is_file():
            raise ValueError(f"Missing package resource: {path}")
    parent.mkdir(parents=True, exist_ok=True)
    # Keep the lock inode stable across invocations; deleting it would introduce
    # concurrent lock races. It is hidden and contains no runtime instructions.
    with (parent / ".geo-audit-install.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another installation is in progress") from None
        stage = Path(tempfile.mkdtemp(prefix=".geo-audit-stage-", dir=parent))
        try:
            shutil.copy2(skill, stage / "SKILL.md")
            shutil.copytree(agents, stage / "agents", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(root / "scripts", stage / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            (stage / "docs").mkdir()
            shutil.copy2(root / "docs/RUN-FORMAT.md", stage / "docs/RUN-FORMAT.md")
            for name in ('AUDIT-DEPTH.md', 'CLIENT-REPORT.md'):
                shutil.copy2(root / 'docs' / name, stage / 'docs' / name)
            hashes = {str(path.relative_to(stage)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in stage.rglob("*") if path.is_file()}
            (stage / "package-manifest.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
            collisions = []
            for role in roles:
                global_role = parent.parent / "agents" / f"{role}.md"
                if global_role.is_file() and global_role.read_bytes() != (stage / "agents" / f"{role}.md").read_bytes():
                    collisions.append(str(global_role))
            backup, pruned = None, 0
            if destination.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                if (destination / ".backups").exists():
                    shutil.copytree(destination / ".backups", stage / ".backups", symlinks=True)
                backup = stage / ".backups" / stamp
                shutil.copytree(destination, backup, symlinks=True,
                                ignore=shutil.ignore_patterns(".backups", "__pycache__"))
                # Backup names are UTC timestamps, so name order is age order.
                backups = [path for path in (stage / ".backups").iterdir() if path.is_dir() and not path.is_symlink()]
                for old in sorted(backups)[:-keep_backups]:
                    shutil.rmtree(old)
                    pruned += 1
                exchange(stage, destination)
                backup = destination / ".backups" / stamp
            else:
                os.rename(stage, destination)
            return {"destination": str(destination), "version": package_version(destination),
                    "backup": str(backup) if backup else None, "pruned_backups": pruned,
                    "different_global_roles": collisions, "files": len(hashes)}
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def package_version(package):
    match = re.search(r'^TOOLKIT_VERSION = "([^"]+)"', (package / "scripts/version.py").read_text(encoding="utf-8"),
                      re.MULTILINE)
    return match[1] if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--keep-backups", type=int, default=KEEP_BACKUPS, help="Number of previous installs to keep")
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.directory, keep_backups=args.keep_backups), indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"Install failed: {exc}\n")


if __name__ == "__main__":
    main()
