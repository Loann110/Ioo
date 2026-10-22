
#/////////////////////////////////////////////
# IMPORTS ////////////////////////////////////
#/////////////////////////////////////////////
import os
import json
import time
import hashlib
from pathlib import Path
#/////////////////////////////////////////////
# SESSION STORAGE ////////////////////////////
#/////////////////////////////////////////////
def store_dir(root, session_id):
    """
    Return the session directory used by F2 and IOO.
    """

    # Match the project/session identifiers used by prepare_f2().
    root = os.path.realpath(root)
    project_id = hashlib.sha256(root.encode()).hexdigest()[:16]
    session_key = hashlib.sha256(session_id.encode()).hexdigest()[:16]

    store = cache_root() / project_id / session_key
    store.mkdir(parents=True, exist_ok=True)
    return store

#/////////////////////////////////////////////
# LOAD CURRENT STATE /////////////////////////
#/////////////////////////////////////////////
def load_state(store, initial_state="A1"):
    """
    Return A1 for a new session; reject a corrupted state file.
    """

    path = Path(store) / "state.json"

    if not path.exists():
        return initial_state

    data = json.loads(path.read_text(encoding="utf-8"))
    state = data["state"]

    if not isinstance(state, str) or not state:
        raise ValueError("Invalid state in state.json")

    return state

#/////////////////////////////////////////////
# SAVE CURRENT STATE /////////////////////////
#/////////////////////////////////////////////
def save_state(store, state):
    """
    Atomically replace state.json with the current GEMMA state.
    """

    write_json(Path(store) / "state.json", {"state":state})

#/////////////////////////////////////////////
# EVENT LOG //////////////////////////////////
#/////////////////////////////////////////////
def log(store, event, state, reason, new_state, extra=None):
    """
    Append one event to events.jsonl without overwriting older events.
    """

    entry = {
        "t": time.time(),
        "event": event,
        "from": state,
        "reason": reason,
        "to": new_state,
    }

    if extra:
        entry.update(extra)

    with (Path(store) / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def cache_root():
    """
    Where Ioo keeps its files.
    Ioo cache lets tests stay out of the user's cache.
    """
    return Path(os.environ.get("IOO_CACHE") or Path.home() / ".cache" / "ioo")

def read_json(path, default=None):
    """ 
    Return the file's JSON content or default when it is missing or corrupted
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except(OSError, ValueError):
        return default
    
def write_json(path, data):
    """ 
    Atomically replace a JSON file
    (A crash never leaves half a file)
    """
    path = Path(path)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)