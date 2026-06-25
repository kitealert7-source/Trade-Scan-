"""Windows-safe recursive directory deletion for the artifact store.

Encodes the deletion hazards hit during the 2026-06-25 uncharged-corpus purge so
no future cleanup re-discovers them (session retro: Windows-deletion friction x3):

  * NTFS junctions (runs/ -> sandbox/, the Atomic-Run-Container v2 pattern): a raw
    recursive delete can FOLLOW a junction and destroy the *target* (the 2026-05-07
    data-loss class). safe_rmtree never recurses into a reparse point -- it removes
    the link with os.rmdir and leaves the junction target untouched.
  * MAX_PATH (260-char) long paths (e.g. 90_PORT_<pair>_..._E######_<pair>/...):
    shutil.rmtree raises WinError 3 ("path not found"). A robocopy /MIR empty-mirror
    handles long paths natively.
  * Read-only attributes (.xlsx / .db sidecars): cleared in the rmtree onerror handler.

Use safe_rmtree() from any tool that deletes artifact-store directories instead of a
bare shutil.rmtree. Reference: outputs/system_reports / the 2026-06-25 session retro.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def is_reparse_point(p) -> bool:
    """True if p is an NTFS junction / symlink (reparse point). Never raises."""
    try:
        return bool(os.lstat(p).st_file_attributes & _REPARSE)
    except (OSError, AttributeError):
        return False


def _onerror(func, path, _exc_info):
    """rmtree onerror: clear the read-only bit and retry once."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _purge(p: str) -> None:
    """Manual recursive remove that NEVER follows a reparse point.

    Finishes off the emptied skeleton + any leftover junctions after the robocopy
    pass. is_reparse_point is checked BEFORE every descent, so a junction is removed
    as a link (os.rmdir) and we never walk into its target.
    """
    if is_reparse_point(p):
        try:
            os.rmdir(p)            # junction/symlink-dir: drop the link, never the target
        except OSError:
            try:
                os.unlink(p)       # symlink-file
            except OSError:
                pass
        return
    if os.path.isdir(p):
        try:
            children = os.listdir(p)
        except OSError:
            children = []
        for child in children:
            _purge(os.path.join(p, child))
        try:
            os.rmdir(p)
        except OSError:
            pass
    else:
        try:
            os.chmod(p, stat.S_IWRITE)
        except OSError:
            pass
        try:
            os.remove(p)
        except OSError:
            pass


def _robocopy_mirror_empty(target: Path) -> None:
    """Empty `target` by mirroring a fresh empty dir into it.

    /XJ => robocopy never recurses INTO a junction (junction-safe); robocopy handles
    MAX_PATH long paths natively where shutil.rmtree cannot. No-op if robocopy is
    absent (non-Windows) -- the caller's _purge pass still runs.
    """
    empty = Path(tempfile.mkdtemp(prefix="_safedel_"))
    try:
        subprocess.run(
            ["robocopy", str(empty), str(target),
             "/MIR", "/XJ", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:0", "/W:0"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    except (FileNotFoundError, OSError):
        pass  # robocopy not available (non-Windows) -- _purge handles it
    finally:
        try:
            os.rmdir(empty)
        except OSError:
            pass


def safe_rmtree(path) -> bool:
    """Delete a directory tree on Windows safely. Returns True if it is gone.

    Junction-safe (never follows reparse points), long-path-safe (robocopy fallback),
    read-only-safe. Drop-in replacement for shutil.rmtree on artifact-store paths.
    """
    path = Path(path)
    if is_reparse_point(path):
        try:
            os.rmdir(path)
        except OSError:
            pass
        return not path.exists()
    if not path.exists():
        return True
    # Fast pass: handles the non-pathological bulk + read-only files.
    shutil.rmtree(path, onerror=_onerror)
    if not path.exists():
        return True
    # Stragglers: MAX_PATH long paths / stubborn junctions. robocopy mirror-empty
    # (long-path + junction safe via /XJ), then a junction-safe manual purge.
    _robocopy_mirror_empty(path)
    _purge(str(path))
    return not path.exists()
