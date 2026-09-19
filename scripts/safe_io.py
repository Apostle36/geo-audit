"""Atomic publication without implicit overwrites (local CLI filesystem scope)."""
import os
from pathlib import Path
import tempfile


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


def atomic_write(source, destination, content, overwrite=False):
    destination = Path(destination)
    check_output(source, destination, overwrite)
    descriptor, name = tempfile.mkstemp(prefix=".geo-output-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        check_output(source, destination, overwrite)
        if overwrite:
            os.replace(temporary, destination)
        else:
            # Atomic no-clobber publication, including simultaneous writers.
            os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
