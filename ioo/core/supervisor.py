#/////////////////////////////////////////////
# IMPORTS ////////////////////////////////////
#/////////////////////////////////////////////
from ioo.F2.f2 import prepare_f2

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
        ("F5", "ok"): "F3",
        ("F5", "fail"): "D2",
        ("D2", "repair"): "F1",
        ("D1", "refused"): "A4",
        ("A4", "resolve"): "F2",
        ("F3", "stop"): "A2",
        ("A2", "new_request"): "A1",
    }
    return transitions.get((state, reason))