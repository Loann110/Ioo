
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

#################################################################################
#################################################################################
# FILE FORMATS AND SYNTAX VERIFICATION ##########################################
#################################################################################
#################################################################################

#/////////////////////////////////////////////
# JSON VERIFICATION //////////////////////////
#/////////////////////////////////////////////
def check_json(files):
    """
    Strict JSON only. JSONC must use a dedicated parser.
    """
    strict = [p for p in files if not JSONC.match(p.name)]

    if not strict:
        return None 

    return _parse_file("json", strict, json.loads)

#/////////////////////////////////////////////
# TOML VERIFICATION //////////////////////////
#/////////////////////////////////////////////
def check_toml(files):
    return _parse_file(
        "toml",
        files,
        tomllib.loads if tomllib else None,
        unsupported="toml_parser_not_installed" if tomllib is None else None,
    )

#/////////////////////////////////////////////
# PYTHON SYNTAX VERIFICATION /////////////////
#/////////////////////////////////////////////
def check_python_syntax(files):
    """
    Compile in memory: catches syntax errors even without tests, writes no .pyc.
    """
    return _parse_file(
        "python_syntax",
        files,
        lambda text: compile(text, "<file>", "exec", dont_inherit=True),
    )


#################################################################################
#################################################################################
# TEST FAILURE ANALYSIS AND DIAGNOSTICS #########################################
#################################################################################
#################################################################################


#/////////////////////////////////////////////
# FAILURE IDENTIFICATION /////////////////////
#/////////////////////////////////////////////
SERVICE_DOWN = re.compile(
    r"Connection refused|ECONNREFUSED|could not connect to server|OperationalError"
    r"|Can't connect to (?:MySQL|local MySQL) server|getaddrinfo ENOTFOUND",
    re.I,
)

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

VOLATILE = re.compile(
    r"0x[0-9a-f]+|\d+(?:\.\d+)?",
    re.I,
)

FAILURE_PATTERNS = [
    # pytest
    re.compile(r"^(?:FAILED|ERROR) (\S+)"),

    # Django / unittest
    re.compile(r"^(?:FAIL|ERROR): (\S+ \([^)]+\))"),

    # Jest
    re.compile(r"^\s*\u25cf (.+?)\s*$"),

    # Vitest
    re.compile(
        r"^\s*(?:FAIL|\u00d7|\u2717)\s+"
        r"(\S+\.[cm]?[jt]sx? > .+?)(?:\s+\d+ms)?\s*$"
    ),

    # TypeScript
    re.compile(r"^(\S+?)\(\d+,\d+\): error (TS\d+: .+)$"),
]


def failure_ids(name, output):
    """
    Extract stable identifiers from failed tests and command output.
    """
    found, lines = [], []

    for line in ANSI.sub("", output or "").splitlines():
        for pattern in FAILURE_PATTERNS:
            match = pattern.match(line)

            if match:
                ident = ": ".join(
                    g for g in match.groups() if g
                )

                if not ident.startswith("Console"):
                    found.append(f"{name}: {ident}")

                break
        else:
            line = VOLATILE.sub("#", line.strip())[:200]

            if line.strip("#-=*_ "):
                lines.append(f"{name}: {line}")

    return sorted(set(found or lines[:200])) or [
        f"{name}: unparsed"
    ]


#/////////////////////////////////////////////
# FAILURE EXCERPTS ///////////////////////////
#/////////////////////////////////////////////
def excerpt(output, ident, extra=3):
    """
    The output line naming one failure, plus the few lines that explain it
    (expected/received, assertion): enough to repair, not the whole log.
    """
    text = ident.split(": ", 1)[-1]
    lines = ANSI.sub("", output or "").splitlines()

    # tsc ids drop the position, so the message alone finds the line.
    for needle in dict.fromkeys((text, text.split(": ", 1)[-1])):
        for i, line in enumerate(lines):
            if needle in line:
                if line.startswith(("FAILED ", "ERROR ")):
                    return line.strip()[:300]

                after = [
                    l.strip()
                    for l in lines[i + 1:i + 15]
                    if l.strip() and not l.strip().startswith("at ")
                ]

                return " | ".join(
                    [line.strip(), *after[:extra]]
                )[:400]

    return text[:300]


#/////////////////////////////////////////////
# COMMAND DISPLAY ////////////////////////////
#/////////////////////////////////////////////
def short_command(command):
    """
    The command as Claude would type it:
    tool name, not its absolute path.
    """
    return " ".join([
        Path(str(command[0])).name,
        *map(str, command[1:]),
    ])

#################################################################################
#################################################################################
# TEST EXECUTION AND CACHE MANAGEMENT ###########################################
#################################################################################
#################################################################################

#/////////////////////////////////////////////
# BYTECODE CACHE /////////////////////////////
#/////////////////////////////////////////////
def pyc_cache():
    return cache_root() / "pyc"


#/////////////////////////////////////////////
# BYTECODE INVALIDATION //////////////////////
#/////////////////////////////////////////////
def forget_bytecode(files):
    """
    .pyc files are trusted on source mtime (whole seconds) and size: a same-size
    edit within a second would run stale code. Drop the changed files' entries.
    Same layout as CPython with PYTHONPYCACHEPREFIX: drive removed, path kept.
    """
    for path in files:
        if Path(path).suffix != ".py":
            continue

        for source in {
            os.path.abspath(path),
            os.path.realpath(path),
        }:
            folder = os.path.dirname(source)

            if len(folder) > 1 and folder[1] == ":":
                folder = folder[2:]

            for pyc in (
                pyc_cache() / folder.lstrip("\\/")
            ).glob(f"{Path(path).stem}.*.pyc"):
                pyc.unlink(missing_ok=True)


#/////////////////////////////////////////////
# LOCAL CHECK EXECUTION //////////////////////
#/////////////////////////////////////////////
def run(name, command, cwd, deadline):
    """
    Run a local command (never a shell or package downloader).
    """
    remaining = deadline - time.monotonic()
    shown = short_command(command)

    if remaining <= 0:
        return result(
            name, "unverified", "time_budget_exhausted", shown
        )

    executable = shutil.which(str(command[0])) or str(command[0])

    try:
        completed = subprocess.run(
            [executable, *map(str, command[1:])],
            cwd=cwd,
            env={
                **os.environ,
                "CI": "true",
                "NO_COLOR": "1",
                "FORCE_COLOR": "0",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPYCACHEPREFIX": str(pyc_cache()),
                "COLUMNS": "200",
            },
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=remaining,
            check=False,
        )

    except FileNotFoundError:
        return result(
            name, "unverified", "tool_not_installed", shown
        )

    except subprocess.TimeoutExpired:
        return result(
            name, "unverified", "timeout", shown
        )

    except OSError as exc:
        return result(
            name,
            "unverified",
            "execution_error",
            shown,
            str(exc)[-OUTPUT_TAIL:],
        )

    full = (completed.stdout + "\n" + completed.stderr).strip()
    output = full[-OUTPUT_TAIL:]

    if completed.returncode == 0:
        return result(
            name, "ok", command=shown, returncode=0
        )

    failed = result(
        name,
        "fail",
        "nonzero_exit",
        shown,
        output,
        completed.returncode,
    )

    failed["failures"] = failure_ids(name, full)
    failed["log"] = full

    return failed


#/////////////////////////////////////////////
# SERVICE AVAILABILITY ///////////////////////
#/////////////////////////////////////////////
def _service_down(outcome):
    """
    A failed test run caused by an unreachable service becomes unverified.
    """
    if (
        outcome["status"] == "fail"
        and SERVICE_DOWN.search(outcome["output"] or "")
    ):
        return result(
            outcome["name"],
            "unverified",
            "service_unavailable",
            outcome["command"],
            returncode=outcome["returncode"],
        )

    return outcome


#/////////////////////////////////////////////
# CHECK COMMAND AGGREGATION //////////////////
#/////////////////////////////////////////////
def run_all(name, commands, cwd, deadline):
    """
    Several commands reported as one check:
    every failure is kept for the comparison.
    """
    outcomes = [
        run(name, command, cwd, deadline)
        for command in commands
    ]

    failed = [
        o for o in outcomes
        if o["status"] == "fail"
    ]

    if failed:
        first = failed[0]

        first["output"] = "\n".join(
            o["output"] or "" for o in failed
        )[-OUTPUT_TAIL:]

        first["failures"] = sorted({
            f
            for o in failed
            for f in o["failures"]
        })

        first["log"] = "\n".join(
            o["log"] for o in failed
        )

        return first

    return next(
        (o for o in outcomes if o["status"] != "ok"),
        outcomes[0],
    )


#/////////////////////////////////////////////
# PYTHON ENVIRONMENT /////////////////////////
#/////////////////////////////////////////////
def python_bin(project):
    project = Path(project)

    for env in (".venv", "venv"):
        for rel in ("Scripts/python.exe", "bin/python"):
            path = project / env / rel

            if path.is_file():
                return str(path)

    return sys.executable


#/////////////////////////////////////////////
# PYTHON TEST EXECUTION //////////////////////
#/////////////////////////////////////////////
def check_python(project, deadline):
    project = Path(project)
    config = project / "pyproject.toml"
    config_text = _read(config) if config.is_file() else ""

    pytest_config = (
        any(
            (project / p).is_file()
            for p in ("pytest.ini", "conftest.py")
        )
        or "[tool.pytest.ini_options]" in config_text
    )

    has_tests = (
        (project / "tests").is_dir()
        or bool(list(project.glob("test_*.py")))
        or bool(list(project.glob("*_test.py")))
    )

    if (project / "manage.py").is_file() and not pytest_config:
        command = [python_bin(project), "manage.py", "test"]

    elif pytest_config or has_tests:
        
        command = [
            python_bin(project),
            "-m", "pytest",
            "-q", "-rfE", "--tb=short",
        ]

    else:
        return result(
            "python",
            "unverified",
            "no_tests_detected",
        )

    outcome = run("python", command, project, deadline)

    if (
        outcome["status"] == "fail"
        and command[1:3] == ["-m", "pytest"]
    ):
        if "No module named pytest" in (outcome["output"] or ""):
            return result(
                "python",
                "unverified",
                "pytest_not_installed",
                outcome["command"],
                returncode=outcome["returncode"],
            )

        if outcome["returncode"] == 5:
            return result(
                "python",
                "unverified",
                "no_tests_collected",
                outcome["command"],
                returncode=5,
            )

    return _service_down(outcome)


#################################################################################
#################################################################################
# NODE.JS PROJECT DISCOVERY AND DEPENDENCIES ####################################
#################################################################################
#################################################################################


#/////////////////////////////////////////////
# WORKSPACE PARENTS //////////////////////////
#/////////////////////////////////////////////
def _parents(project, root=None):
    """
    The project folder, then its parents up to the repository root.
    Workspaces (npm, pnpm, yarn) install node_modules at the root.
    """
    folder = Path(project).resolve()
    stop = Path(root).resolve() if root else folder

    while True:
        yield folder

        if folder == stop or folder == folder.parent:
            return

        folder = folder.parent

#/////////////////////////////////////////////
# NODE DEPENDENCIES //////////////////////////
#/////////////////////////////////////////////
def node_modules(project, root=None):
    """
    Nearest node_modules folder, or None.
    """
    for folder in _parents(project, root):
        if (folder / "node_modules").is_dir():
            return folder / "node_modules"

    return None

#/////////////////////////////////////////////
# LOCAL NODE EXECUTABLES /////////////////////
#/////////////////////////////////////////////
def local_bin(project, name, root=None):
    """
    Executable installed in this project's (or the workspace's) node_modules.
    """
    suffixes = (
        (".cmd", "") if os.name == "nt"
        else ("", ".cmd")
    )

    for folder in _parents(project, root):
        for suffix in suffixes:
            path = (
                folder / "node_modules" /
                ".bin" / (name + suffix)
            )

            if path.is_file():
                return str(path)

    return None

#/////////////////////////////////////////////
# PACKAGE MANIFEST ///////////////////////////
#/////////////////////////////////////////////
def _package(project):
    path = Path(project) / "package.json"

    if not path.is_file():
        return None

    try:
        data = json.loads(_read(path))
        return data if isinstance(data, dict) else None

    except (ValueError, OSError):
        return None

#/////////////////////////////////////////////
# PACKAGE DEPENDENCIES ///////////////////////
#/////////////////////////////////////////////
def _dependencies(manifest):
    dependencies = manifest.get("dependencies") or {}
    dev_dependencies = manifest.get("devDependencies") or {}

    if (
        not isinstance(dependencies, dict)
        or not isinstance(dev_dependencies, dict)
    ):
        return {}

    return {
        **dependencies,
        **dev_dependencies,
    }


#/////////////////////////////////////////////
# FRAMEWORK DETECTION ////////////////////////
#/////////////////////////////////////////////
def framework_name(manifest):
    """
    Classify frameworks for reporting, not for claiming test coverage.
    """
    deps = _dependencies(manifest)

    for package, label in (
        ("next", "nextjs"),
        ("nuxt", "nuxt"),
        ("@nestjs/core", "nestjs"),
        ("fastify", "fastify"),
        ("express", "express"),
        ("@sveltejs/kit", "sveltekit"),
        ("svelte", "svelte"),
        ("vue", "vue"),
        ("react", "react"),
    ):
        if package in deps:
            return label

    return "javascript"


#################################################################################
#################################################################################
# NODE.JS TEST EXECUTION AND SYNTAX VERIFICATION ################################
#################################################################################
#################################################################################

#/////////////////////////////////////////////
# PLAYWRIGHT E2E TESTS ///////////////////////
#/////////////////////////////////////////////
def check_playwright(project, deadline):
    """
    E2E may access live services or write data:
    require explicit future opt-in.
    """
    return result(
        "playwright",
        "unverified",
        "e2e_requires_opt_in",
    )


#/////////////////////////////////////////////
# JAVASCRIPT TEST EXECUTION //////////////////
#/////////////////////////////////////////////
def check_javascript(project, deadline, root=None):
    """
    Run only an existing test script with a locally available package manager.
    """
    manifest = _package(project)

    if manifest is None:
        return result(
            "javascript",
            "unverified",
            "package_json_missing_or_invalid",
        )

    name = framework_name(manifest)
    scripts = manifest.get("scripts")
    script = scripts.get("test", "") if isinstance(scripts, dict) else ""

    if (
        not isinstance(script, str)
        or not script.strip()
        or "no test specified" in script.lower()
    ):
        return result(name, "unverified", "no_test_script")

    test_script = "test"

    if "playwright" in script.lower():
        # Unit tests still run when a separate script holds them.
        unit = next(
            (
                s for s in ("test:unit", "unit")
                if isinstance(scripts.get(s), str)
                and "playwright" not in scripts[s].lower()
            ),
            None,
        )

        if unit is None:
            return check_playwright(project, deadline)

        test_script = unit

    if (
        manifest.get("dependencies")
        or manifest.get("devDependencies")
    ) and node_modules(project, root) is None:
        return result(
            name,
            "unverified",
            "node_dependencies_not_installed",
        )

    project = Path(project)

    # Workspaces keep the lockfile at the repository root.
    locks = {
        lock.name
        for folder in _parents(project, root)
        for lock in folder.glob("*.lock*")
    }

    if any(
        (folder / "pnpm-lock.yaml").exists()
        for folder in _parents(project, root)
    ):
        locks.add("pnpm-lock.yaml")

    if "pnpm-lock.yaml" in locks:
        command = ["pnpm", "run", test_script]

    elif "yarn.lock" in locks:
        command = ["yarn", "run", test_script]

    elif locks & {"bun.lock", "bun.lockb"}:
        command = ["bun", "run", test_script]

    else:
        command = ["npm", "run", test_script, "--silent"]

    return _service_down(
        run(name, command, project, deadline)
    )


#/////////////////////////////////////////////
# NODE SYNTAX VERIFICATION ///////////////////
#/////////////////////////////////////////////
BUNDLED = {
    "react",
    "preact",
    "next",
    "vue",
    "nuxt",
    "svelte",
    "@sveltejs/kit",
    "solid-js",
}


def check_node_syntax(project, files, deadline):
    """
    node --check on plain JS (Node backends, scripts): syntax only.
    Skipped for bundled frontends (JSX in .js) and Node < 22
    (no ESM detection).
    """
    node = shutil.which("node")

    existing = [
        p for p in files
        if p.is_file()
        and p.suffix.lower() in (".js", ".mjs", ".cjs")
    ][:50]

    if (
        not node
        or not existing
        or BUNDLED & set(
            _dependencies(_package(project) or {})
        )
    ):
        return None

    try:
        version = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout

        if int(
            version.strip().lstrip("v").split(".")[0]
        ) < 22:
            return None

    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return None

    return run_all(
        "node_syntax",
        [
            [node, "--check", str(p)]
            for p in existing
        ],
        project,
        deadline,
    )
