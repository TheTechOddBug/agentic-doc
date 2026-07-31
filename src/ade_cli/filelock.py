"""Cross-platform advisory file lock — the one module allowed to import
platform-specific locking primitives (fcntl on POSIX, msvcrt on Windows),
so the frozen binary starts everywhere. Same advisory posture as before:
every mutator is this CLI."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if os.name == "nt":
    import msvcrt

    @contextmanager
    def exclusive(path: Path) -> Iterator[None]:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            # LK_LOCK gives up after ~10s; loop for flock-like indefinite
            # blocking (the refresh lock is legitimately held across a
            # token-refresh network call). It sleeps ~1s per attempt
            # internally, so the loop isn't hot.
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
            try:
                yield
            finally:
                # Unlock the same byte range: the fd is never written, but
                # re-seek to 0 so the range can't drift.
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)

else:
    import fcntl

    @contextmanager
    def exclusive(path: Path) -> Iterator[None]:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
