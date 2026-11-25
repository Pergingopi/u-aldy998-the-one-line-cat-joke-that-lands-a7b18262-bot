#!/usr/bin/env python3
"""The One-Line Cat Joke That Lands — make.fun entry.

Writes exactly one joke about cats — a single line of 1-200 characters,
with no trailing newline — to ``$MAKEFUN_OUTPUT_DIR/entry.txt``
(default ``/output``).

The joke is fixed at build time so every run produces byte-identical
output: the same text is written on every run, by every user, in every
environment. Python 3.13 standard library only; no network, no clock,
no randomness anywhere in the write path.
"""

import os
import sys
import tempfile
import time

# The entry: setup (cat parks herself on the laptop mid-call) then a
# turn (she gets promoted, because lying down on the job is now
# leadership). Short, retellable, and the punchline reuses the setup
# instead of explaining it.
ENTRY_TEXT = (
    "My cat sat on my laptop during a work call and got promoted "
    "\u2014 apparently lying down on the job is leadership now."
)

MAX_CHARS = 200
OUTPUT_FILENAME = "entry.txt"
TMP_PREFIX = ".entry-"
TMP_SUFFIX = ".tmp"

# Stale temp files left behind by a killed earlier run are older than
# this many seconds before we try to remove them.
STALE_TMP_AGE_SECONDS = 3600.0
CLEANUP_ATTEMPTS = 3
CLEANUP_RETRY_DELAY_SECONDS = 0.05


def _fail(message: str) -> ValueError:
    """Build the validation error for *message*.

    Every failure in this module is raised explicitly as a typed
    exception with a human-readable message; nothing here relies on
    ``assert``, which a ``-O`` run would silently drop.
    """
    return ValueError(message)


def _check_not_blank(text: str) -> None:
    """Reject empty or whitespace-only entries."""
    if not text or not text.strip():
        raise _fail("entry must be non-empty and not only whitespace")


def _check_length(text: str) -> None:
    """Reject entries over the competition's character gate."""
    if len(text) > MAX_CHARS:
        raise _fail(
            f"entry is {len(text)} characters, over the {MAX_CHARS} limit"
        )


def _check_single_line(text: str) -> None:
    """Reject anything that is not exactly one line of text."""
    if "\n" in text or "\r" in text:
        raise _fail("entry must be a single line (no CR or LF)")


def _check_printable(text: str) -> None:
    """Reject control characters, which can never be part of the joke."""
    for ch in text:
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            raise _fail(
                f"entry contains a control character U+{code:04X}"
            )


def validate_entry(text: str) -> None:
    """Run every gate check on *text*, raising on the first failure.

    Split into one small check per rule so a failing run names the
    exact rule that broke instead of a generic "invalid entry".
    """
    _check_not_blank(text)
    _check_length(text)
    _check_single_line(text)
    _check_printable(text)


def resolve_output_dir() -> str:
    """Return the directory ``entry.txt`` will be written into.

    ``MAKEFUN_OUTPUT_DIR`` wins when it names a real directory; an
    unset variable, an empty string, or a whitespace-only value all
    fall back to ``/output`` instead of crashing on a bogus path.
    """
    raw = os.environ.get("MAKEFUN_OUTPUT_DIR")
    if raw is not None:
        cleaned = raw.strip()
        if cleaned:
            return cleaned
    return "/output"


def _is_stale_tmp_file(path: str, now: float) -> bool:
    """True when *path* is one of our temp files and old enough to reap."""
    name = os.path.basename(path)
    if not name.startswith(TMP_PREFIX) or not name.endswith(TMP_SUFFIX):
        return False
    try:
        return now - os.stat(path).st_mtime > STALE_TMP_AGE_SECONDS
    except OSError:
        return False


def cleanup_stale_tmp_files(out_dir: str) -> None:
    """Best-effort removal of stale ``.entry-*.tmp`` files in *out_dir*.

    A previous run killed mid-write can leave a temp file behind; over
    many runs those pile up. Each candidate is unlinked with a few
    retries (another process may still hold it), and any failure is
    swallowed — leftover temp files are untidy, never fatal, and must
    not stop a valid entry from being written.
    """
    try:
        names = os.listdir(out_dir)
    except OSError:
        return
    now = time.time()
    for name in names:
        path = os.path.join(out_dir, name)
        if not _is_stale_tmp_file(path, now):
            continue
        for attempt in range(CLEANUP_ATTEMPTS):
            try:
                os.unlink(path)
                break
            except OSError:
                if attempt < CLEANUP_ATTEMPTS - 1:
                    time.sleep(CLEANUP_RETRY_DELAY_SECONDS)


def _fsync_dir(out_dir: str) -> None:
    """Flush *out_dir* itself so the rename below is durable on disk."""
    dir_fd = os.open(out_dir, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _atomic_write(out_dir: str, data: bytes) -> str:
    """Write *data* to ``entry.txt`` in *out_dir* via temp file + rename.

    Returns the full path of the finished file. The temp file is
    created in the same directory so the rename is atomic, is given
    mode 0644 before the rename, and is removed again on any failure
    so a failed run never leaves a half-written entry behind.
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=out_dir, prefix=TMP_PREFIX, suffix=TMP_SUFFIX
    )
    try:
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(tmp_path, 0o644)
        target = os.path.join(out_dir, OUTPUT_FILENAME)
        os.replace(tmp_path, target)
        os.chmod(target, 0o644)
        _fsync_dir(out_dir)
        return target
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _verify_written(target: str, data: bytes) -> None:
    """Read *target* back and confirm it holds exactly *data* at 0644."""
    with open(target, "rb") as fh:
        if fh.read() != data:
            raise RuntimeError("read-back verification failed")
    mode = os.stat(target).st_mode & 0o777
    if mode != 0o644:
        raise RuntimeError(f"entry.txt mode is {mode:03o}, not 0644")


def main() -> int:
    """Validate the joke, write it atomically, verify it, and exit 0."""
    validate_entry(ENTRY_TEXT)
    out_dir = resolve_output_dir()
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        raise RuntimeError(f"output path {out_dir!r} is not a directory")
    os.makedirs(out_dir, exist_ok=True)
    cleanup_stale_tmp_files(out_dir)
    data = ENTRY_TEXT.encode("utf-8")
    target = _atomic_write(out_dir, data)
    _verify_written(target, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
