#/////////////////////////////////////////////
# IMPORTS ////////////////////////////////////
#/////////////////////////////////////////////
import json
import os
import re
from pathlib import Path

from ioo.F2.f2 import snapshot, changes

#/////////////////////////////////////////////
# GLOBALS ////////////////////////////////////
#/////////////////////////////////////////////
FILE_TOOLS = {
    "Write": "file_path", "Edit": "file_path",
    "MultiEdit": "file_path", "NotebookEdit": "notebook_path",
}
# Limited, deterministic alerts
# Not a comprehensive security sandbox yet.
RISKY_COMMANDS = [
    (r"\brm\s+-(?=[a-z]*r)(?=[a-z]*f)[a-z]*\b", "recursive forced delete"),
    (r"\brm\s+--recursive\s+--force\b", "recursive forced delete"),
    (r"\bgit\s+push\b[^\n]*?(?:--force(?:-with-lease)?\b|\s-f\b)", "force push"),
    (r"\bgit\s+reset\s+--hard\b", "hard reset"),
    (r"\bgit\s+clean\s+-(?=[a-z]*f)[a-z]*\b", "git clean"),
    (r"\bsudo\b", "sudo"),
    (r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba)?sh\b", "remote script piped to shell"),
    (r"\b(?:mkfs(?:\.\w+)?|dd\s+if=)\b", "disk-level command"),
    (r"\bRemove-Item\b[^\n]*\b-Recurse\b", "recursive PowerShell delete"),
]

#/////////////////////////////////////////////
# OBSERVE TOOL CALLS /////////////////////////
#/////////////////////////////////////////////
def observe_tool(tool, tool_input):
    """
    Record only tool and path metadata, never raw shell commands.
    """
    tool_input = tool_input or {}
    target = ""
    for key in ("file_path", "notebook_path", "path"):
        if tool_input.get(key):
            target = str(tool_input[key])[:200]
            break
    return {"tool": tool, "target": target}

#/////////////////////////////////////////////
# ANOMALIES //////////////////////////////////
#/////////////////////////////////////////////
def anomalies(root, tool, tool_input):
    """
    Recognize a limited set of suspicious tool calls before execution.
    """
    found = []
    
    tool_input = tool_input or {}
    if tool in ("Bash", "PowerShell"):
        command = tool_input.get("command", "")
        for pattern, label in RISKY_COMMANDS:
            if re.search(pattern, command, flags=re.IGNORECASE):
                found.append(label)
                
    elif tool in FILE_TOOLS:
        path = tool_input.get(FILE_TOOLS[tool])
        if path:
            root_real = os.path.realpath(root)
            real = os.path.realpath(os.path.join(root_real, path))
            try:
                outside = os.path.commonpath([root_real, real]) != root_real
            except ValueError:  
                outside = True
            if outside:
                found.append("write outside project")
            if ".git" in (x.lower() for x in Path(real).parts):
                found.append("write inside .git")
            name = os.path.basename(real).lower()
            if name.startswith(".env") or name.endswith((".pem", ".key")):
                found.append("write to sensitive file")
    
    return found

#/////////////////////////////////////////////
# END OF CLAUDE'S TURN ///////////////////////
#/////////////////////////////////////////////
def end_of_turn(root, store):
    """
    Compare monitored files with F2 and request tests if any changed.
    """
    baseline = json.loads((Path(store) / "baseline.json").read_text(encoding="utf-8"))
    current, _ = snapshot(os.path.realpath(root), baseline["files"])
    diff = changes(baseline["files"], current)
    
    if not any(diff.values()):
        return {"event": "no_change"}
    return {"event": "test", **diff}
