#/////////////////////////////////////////////
# IMPORTS ////////////////////////////////////
#/////////////////////////////////////////////
import json
from pathlib import Path
from ioo.core import registry
from ioo.F2 import f2
from ioo.F2.f2 import prepare_f2
from ioo.F1 import f1
from ioo.F5 import f5
from ioo.D2 import d2

#/////////////////////////////////////////////
# GLOBALS ////////////////////////////////////
#/////////////////////////////////////////////
INITIAL_STATE = "A1"
VALID_STATES = {"A1", "F2", "F1", "F5", "D2", "D1", "A4", "F3", "A2"}

#/////////////////////////////////////////////
# GEMMA TRANSITIONS //////////////////////////
#/////////////////////////////////////////////
def transition(state, reason):
    """
    Return the next GEMMA state, or None for invalid transitions.
    """
    transitions = {
        ("A1", "request"): "F2",
        ("F2", "prepared"): "F1",
        ("F2", "risky"): "D1",
        ("F1", "test"): "F5",
        ("F1", "risky"): "D1",
        ("F1", "no_change"): "F3", 
        ("F5", "ok"): "F3",
        ("F5", "fail"): "D2",
        ("F5", "unverified"): "F3", 
        ("F5", "preexisting"): "F3",
        ("D2", "repair"): "F1",
        ("D2", "give_up"): "A4", 
        ("D1", "refused"): "A4",
        ("A4", "resolve"): "F2",
        ("F3", "stop"): "A2",
        ("A2", "new_request"): "A1",
    }
    return transitions.get((state, reason))

#/////////////////////////////////////////////
# SUPERVISOR ENTRY POINT /////////////////////
#/////////////////////////////////////////////
def new_failures(store, result):
    """
    Failures of this verification that were not in F2's reference.
    
    """
    try:
        reference = json.loads((Path(store) / "baseline.json").read_text(encoding="utf-8")).get("reference") or {}
    
    except (OSError, ValueError):
        reference = {}
        
    old = set(reference.get("failures") or [])
    now = set(result.get("failures") or [])
    
    # Unparsed output cannot be compared: always treated as new.
    return sorted(f for f in now if f not in old or f.endswith(": unparsed")), sorted(now & old)


