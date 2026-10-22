
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
