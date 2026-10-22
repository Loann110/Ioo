
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
    
#/////////////////////////////////////////////
# FILE PARSING ///////////////////////////////
#/////////////////////////////////////////////
def _parse_file(name, files, parser, unsupported=None):
    """
    Parse the existing files independently and aggregate their results.
    """
    if unsupported:
        return result(name, "unverified", unsupported)

    errors, count = [], 0

    for path in files:
        if not path.is_file():
            continue  # A deleted file cannot be parsed.

        count += 1

        try:
            parser(_read(path, strict=True))
        except (OSError, ValueError, UnicodeError, SyntaxError) as exc:
            errors.append(f"{path.name}: {str(exc)[:160]}")

    if errors:
        failed = result(
            name,
            "fail",
            "invalid_syntax",
            output="\n".join(errors)[-OUTPUT_TAIL:],
        )
        failed["failures"] = [
            f"{name}: {error}" for error in errors
        ]
        failed["log"] = "\n".join(errors)
        return failed

    return result(name, "ok") if count else None
