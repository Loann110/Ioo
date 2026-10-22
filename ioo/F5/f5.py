
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
