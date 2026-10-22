
#/////////////////////////////////////////////
# IMPORTS ////////////////////////////////////
#/////////////////////////////////////////////
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ioo.core.registry import cache_root

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

#/////////////////////////////////////////////
# GLOBALS ////////////////////////////////////
#/////////////////////////////////////////////
OUTPUT_TAIL = 3000

# Results that depend on time, services or IOO itself:
# never reused, always re-run.
VOLATILE_REASONS = {
    "timeout",
    "time_budget_exhausted",
    "service_unavailable",
    "check_error",
    "execution_error",
}

JSONC = re.compile(
    r"^(?:tsconfig.*|jsconfig.*|\.eslintrc|devcontainer)\.json$",
    re.I,
)

#/////////////////////////////////////////////
# CHECK RESULT ///////////////////////////////
#/////////////////////////////////////////////
def result(name, status, reason=None, command=None, output=None, returncode=None):
    """
    One check result.
    Only executed successful checks may return 'ok'.
    """
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "command": command,
        "output": output,
        "returncode": returncode,
    }

#/////////////////////////////////////////////
# FILE READING ///////////////////////////////
#/////////////////////////////////////////////
def _read(path, strict=False):
    """
    Strict decoding only where the encoding itself is being checked.
    """
    return Path(path).read_text(
        encoding="utf-8",
        errors="strict" if strict else "replace",
    )