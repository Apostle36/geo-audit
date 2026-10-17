"""Atomic publication without implicit overwrites (local CLI filesystem scope)."""
import os
from pathlib import Path
import secrets


def check_output(source, destination, overwrite=False):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Input and output must be different files")
    if destination.exists() and os.path.samefile(source, destination):
        raise ValueError("Input and output refer to the same inode")
    if destination.is_symlink():
        raise ValueError("Refusing a symlink output")
    if destination.exists() and (not overwrite or not destination.is_file()):
        raise FileExistsError("Output already exists; choose another path or explicitly use --overwrite")
    if not destination.parent.is_dir():
        raise ValueError("Output parent directory must exist")


def check_new(destination):
    destination = Path(destination)
    if destination.is_symlink() or destination.exists():
        raise FileExistsError(f"Output already exists; choose another path: {destination}")
    if not destination.parent.is_dir():
        raise ValueError("Output parent directory must exist")


def atomic_write(source, destination, content, overwrite=False):
    destination = Path(destination)
    check_output(source, destination, overwrite)
    _publish(destination, content, overwrite, lambda: check_output(source, destination, overwrite))


def write_new(destination, content):
    """Publish a file that has no input to protect, never replacing an existing path."""
    destination = Path(destination)
    check_new(destination)
    _publish(destination, content, False, lambda: check_new(destination))


def _publish(destination, content, overwrite, recheck):
    descriptor, temporary = _temporary(destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        recheck()
        if overwrite:
            os.replace(temporary, destination)
        else:
            # Atomic no-clobber publication, including simultaneous writers.
            os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _temporary(directory):
    # Unlike mkstemp's fixed 0600, the creation mode lets the caller's umask decide
    # who can read a delivered report, as for any other file the user creates.
    for _ in range(100):
        name = directory / f".geo-output-{secrets.token_hex(8)}"
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            return os.open(name, flags, 0o666), name
        except FileExistsError:
            continue
    raise FileExistsError("Could not create a unique temporary output")
