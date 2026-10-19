#/////////////////////////////////////////////
# IMPORTS ////////////////////////////////////
#/////////////////////////////////////////////
import os
import hashlib 
import time
import subprocess
import json
from pathlib import Path
#/////////////////////////////////////////////
# GLOBALS ////////////////////////////////////
#/////////////////////////////////////////////
IGNORE_DIRS = {
    # versioning
    ".git",
    
    # Dependencies
    "node_modules", ".venv", "venv",
    
    # Caches
    "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache",
    ".cache", ".turbo",
    
    # Builds
    "dist", "build", "builds", ".next", ".nuxt",
    ".output", "coverage", "htmlcov",
    
    # Temporary files
    "tmp", "temp"
}

MAX_FILE_BYTES = 2_000_000

#################################################################################
#################################################################################
# FILES AND PHOTOGRAPHY OF THE PROJECT ##########################################
#################################################################################
#################################################################################

#////////////////////////////////////////////////////////////////////////////////
# LIST PROJECT FILES ////////////////////////////////////////////////////////////
#////////////////////////////////////////////////////////////////////////////////
def project_files(root):
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and not d.startswith("."))

        for name in sorted(names):
            path = os.path.join(folder, name)

            if name.startswith(".env") or name.endswith((".pem", ".key")):
                continue

            if os.path.getsize(path) <= MAX_FILE_BYTES:
                yield os.path.relpath(path, root).replace("\\", "/")

#////////////////////////////////////////////////////////////////////////////////
# SNAPSHOT //////////////////////////////////////////////////////////////////////
#////////////////////////////////////////////////////////////////////////////////
def snapshot(root, previous):
    """
    Returns (snap, ts) where:
        - snap = {file: [size, modification_time, sha256]},
            reusable as the previous snapshot.
        - ts = UNIX timestamp indicating when the snapshot was taken.
        The hash is recalculated only if the file has changed.
    """
    files = {}

    for rel in project_files(root):
        path = os.path.join(root, rel)
        st = os.stat(path)
        old = previous.get(rel)

        if old and old[:2] == [st.st_size, st.st_mtime_ns]:
            files[rel] = old
        else:
            with open(path, "rb") as f:
                files[rel] = [st.st_size, st.st_mtime_ns,
                hashlib.sha256(f.read()).hexdigest()]

    return files, time.time()
#////////////////////////////////////////////////////////////////////////////////
# RETRIEVING GIT INFOS //////////////////////////////////////////////////////////
#////////////////////////////////////////////////////////////////////////////////
def git(root, *args):
    try:
        result = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""
#////////////////////////////////////////////////////////////////////////////////
# COMPARISON OF SNAPSHOTS ///////////////////////////////////////////////////////
#////////////////////////////////////////////////////////////////////////////////
def changes(before, after):
    return {
        "added": [r for r in after if r not in before],
        "modified": [r for r in after if r in before and after[r][2] != before[r][2]],
        "deleted": [r for r in before if r not in after],
    }

#////////////////////////////////////////////////////////////////////////////////
# REFERENCE CHECKS (state of the tests before Claude works) /////////////////////
#////////////////////////////////////////////////////////////////////////////////
def snapshot_digest(files):
    """
    One hash for the whole snapshot: same digest = same project content.
    """
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode())
        h.update(files[rel][2].encode())
    return h.hexdigest()


def reference_path(store):
    """
    Stored at project level (shared by sessions), not per session.
    """
    return Path(store).parent / "reference_checks.json"


def save_reference(store, files, result):
    """
    Record which checks fail for this exact project content.
    Called by F2, and by the supervisor after F5 so the next prompt can reuse it.
    """
    reference = {
        "digest": snapshot_digest(files),
        "timestamp": time.time(),
        "event": result.get("event"),
        "failures": sorted(set(result.get("failures") or [])),
        "checks": result.get("checks") or [],
    }
    tmp = reference_path(store).with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(reference, indent=2), encoding="utf-8")
    tmp.replace(reference_path(store))
    return reference


def reference_checks(root, store, files, verify=None):
    """
    Failures that already exist before Claude starts.

    Reuses the stored result when the project content is unchanged
    (typically: F5 ended the previous turn on this exact state).
    Otherwise runs `verify(root, None)` once. Without a verifier, returns None.
    """
    digest = snapshot_digest(files)
    try:
        cached = json.loads(reference_path(store).read_text(encoding="utf-8"))
        if cached.get("digest") == digest:
            return dict(cached, source="cache")
    except (OSError, ValueError):
        pass

    if verify is None:
        return None

    return dict(save_reference(store, files, verify(root, None)), source="run")


#////////////////////////////////////////////////////////////////////////////////
# F2 PREPARATION ////////////////////////////////////////////////////////////////
#////////////////////////////////////////////////////////////////////////////////
def prepare_f2(root, session_id, verify=None):
    """
    Capture and save the initial project state.

    Parameters
    ----------
    root : str
        Path to the project directory.
    session_id : str
        Unique identifier of the Claude Code session.
    verify : callable, optional
        F5's verify(root, changed), injected by the supervisor, used to record
        which checks already fail before Claude starts.

    Returns
    -------
    dict
        Preparation event, baseline path and file count.
    """

    # Resolve the project path.
    root = os.path.realpath(root)

    # Create a unique storage directory for the project and session.
    project_id = hashlib.sha256(root.encode()).hexdigest()[:16]
    session_key = hashlib.sha256(session_id.encode()).hexdigest()[:16]

    store = Path.home() / ".cache" / "ioo" / project_id / session_key
    store.mkdir(parents=True, exist_ok=True)

    # Capture the initial project snapshot.
    files, timestamp = snapshot(root, {})

    # Collect the initial project state.
    baseline = {
        "timestamp": timestamp,
        "files": files,
        "git_head": git(root, "rev-parse", "HEAD"),
        "git_status": git(root, "status", "--short"),
        "reference": reference_checks(root, store, files, verify),
    }

    # Save the baseline to disk.
    baseline_path = store / "baseline.json"

    with baseline_path.open("w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)

    # Notify the GEMMA supervisor that F2 preparation is complete.
    return {
        "event": "prepared",
        "baseline": str(baseline_path),
        "files_count": len(files),
        "reference": (baseline["reference"] or {}).get("source"),
    }