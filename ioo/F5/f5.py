
#/////////////////////////////////////////////
# IMPORTS ////////////////////////////////////
#/////////////////////////////////////////////
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

from ioo.core import registry
from ioo.F5 import languages as lang
from ioo.F2.f2 import IGNORE_DIRS


#/////////////////////////////////////////////
# GLOBALS ////////////////////////////////////
#/////////////////////////////////////////////
TIME_BUDGET = 150

MARKERS = {
    "package.json",
    "pyproject.toml",
    "pytest.ini",
    "manage.py",
    "tsconfig.json",
    "go.mod",
    "Cargo.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "conftest.py",
}

NODE_EXT = {
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx", ".vue", ".svelte",
}

TS_EXT = {".ts", ".tsx", ".vue", ".svelte"}

CODE_EXT = NODE_EXT | {".py"}


#/////////////////////////////////////////////
# PROJECT ROOT DETECTION /////////////////////
#/////////////////////////////////////////////
def project_for(root, path):
    """
    Choose the nearest parent carrying a project marker.
    """
    folder = path if path.is_dir() else path.parent

    while True:
        if any((folder / marker).exists() for marker in MARKERS):
            return folder

        if folder == root or folder == folder.parent:
            return root

        folder = folder.parent


#/////////////////////////////////////////////
# SOURCE FILE DISCOVERY //////////////////////
#/////////////////////////////////////////////
def scan_files(root):
    """
    Bounded discovery when F1 did not supply a change list.
    """
    selected = []

    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(
            d for d in dirs
            if d not in IGNORE_DIRS and not d.startswith(".")
        )

        if len(Path(folder).relative_to(root).parts) >= 4:
            dirs.clear()

        for name in sorted(names):
            if len(selected) >= 1000:
                return selected

            path = Path(folder) / name

            if path.is_symlink():
                continue

            if (
                path.suffix.lower() in (
                    NODE_EXT | {
                        ".py", ".html", ".htm",
                        ".css", ".scss", ".json",
                        ".toml", ".yaml", ".yml",
                        ".sql", ".prisma",
                    }
                )
                or name == ".env.example"
            ):
                selected.append(path)

    return selected


#/////////////////////////////////////////////
# CHANGED FILE NORMALIZATION /////////////////
#/////////////////////////////////////////////
def changed_files(root, changed):
    """
    Turn F1's relative paths into safe project-contained Path values.
    """
    if changed is None:
        return scan_files(root)

    if isinstance(changed, dict):
        changed = [
                    *changed.get("added", []),
                    *changed.get("modified", []),
                    *changed.get("deleted", []),
                    ]

    paths = []

    for item in changed:
        candidate = (root / item).resolve()

        if not candidate.is_relative_to(root):
            raise ValueError(f"File outside project: {item}")

        paths.append(candidate)

    return list(dict.fromkeys(paths))


#/////////////////////////////////////////////
# CHECK SUMMARY //////////////////////////////
#/////////////////////////////////////////////
def _summary(checks):
    """
    Log metadata only
    stderr/stdout stays out of the event registry.
    """
    return [
        {
            k: c[k]
            for k in ("name", "project", "status", "reason")
        }
        for c in checks
    ]


#/////////////////////////////////////////////
# CHECK DISPATCHER ///////////////////////////
#/////////////////////////////////////////////
def _checks(project, files, deadline, root):
    """
    Execute only checks supported at this stage.
    """
    by_ext = {}

    for path in files:
        by_ext.setdefault(path.suffix.lower(), []).append(path)

    suffixes = set(by_ext)

    if ".json" in suffixes:
        yield lang.check_json(by_ext[".json"])

    if ".toml" in suffixes:
        yield lang.check_toml(by_ext[".toml"])

    if ".py" in suffixes:
        yield lang.check_python_syntax(by_ext[".py"])


#/////////////////////////////////////////////
# F5 VERIFICATION ORCHESTRATOR ///////////////
#/////////////////////////////////////////////
def verify(root, changed=None, budget=None):
    """
    Verify applicable files without invoking any language model.
    """
    root = Path(root).resolve()

    if not root.is_dir():
        return {
            "event": "unverified",
            "reason": "project_not_found",
            "checks": [],
        }

    try:
        files = changed_files(root, changed)
    except (ValueError, TypeError) as exc:
        return {
            "event": "unverified",
            "reason": "invalid_file_paths",
            "checks": [],
            "detail": str(exc),
        }

    groups = {}

    for path in files:
        project = project_for(root, path)
        groups.setdefault(project, []).append(path)

    checks = []
    deadline = time.monotonic() + (
        TIME_BUDGET if budget is None else budget
    )

    for project, paths in sorted(
        groups.items(),
        key=lambda pair: str(pair[0]),
    ):
        outcomes = _checks(project, paths, deadline, root)

        for outcome in outcomes:
            if outcome is None:
                continue

            outcome["project"] = (
                str(project.relative_to(root)) or "."
            )
            checks.append(outcome)

    failed = [
        c for c in checks
        if c["status"] == "fail"
    ]

    if failed:
        first = failed[0]

        return {
            "event": "fail",
            "reason": first.get("reason"),
            "check": first["name"],
            "command": first.get("command"),
            "output": first.get("output"),
            "returncode": first.get("returncode"),
            "failures": sorted({
                f
                for c in failed
                for f in c.get("failures", [])
            }),
            "failed": [
                {
                    "name": c["name"],
                    "project": c["project"],
                    "command": c.get("command"),
                    "returncode": c.get("returncode"),
                    "excerpts": {},
                }
                for c in failed
            ],
            "checks": _summary(checks),
            "logs": [],
        }

    if checks and all(
        c["status"] == "ok" for c in checks
    ):
        return {
            "event": "ok",
            "checks": _summary(checks),
        }

    return {
        "event": "unverified",
        "reason": (
            "no_applicable_checks"
            if not checks else "incomplete_coverage"
        ),
        "checks": _summary(checks),
        "logs": [],
    }


#/////////////////////////////////////////////
# SAFE CHECK EXECUTION ///////////////////////
#/////////////////////////////////////////////
def _safe(outcomes):
    """
    A crashing check must not disable F5: report it as unverified and
    stop checking this project.
    """
    try:
        yield from outcomes
    except Exception as exc:
        crashed = lang.result(
            "internal",
            "unverified",
            "check_error",
            output=f"{type(exc).__name__}: {exc}"[:300],
        )
        crashed["log"] = traceback.format_exc()
        yield crashed
