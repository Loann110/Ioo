
#/////////////////////////////////////////////
# IMPORTS ////////////////////////////////////
#/////////////////////////////////////////////
from ioo.F2.f2 import prepare_f2

#/////////////////////////////////////////////
# GLOBALS ////////////////////////////////////
#/////////////////////////////////////////////
INITIAL_STATE = "A1"
#/////////////////////////////////////////////
# GEMMA TRANSITIONS //////////////////////////
#/////////////////////////////////////////////
def transition(state, reason):

    if state == "A1":
        if reason == "request":
            return "F2"

    if state == "F2":
        if reason == "prepared":
            return "F1"
        elif reason == "risky":
            return "D1"

    if state == "F1":
        if reason == "test":
            return "F5"

    if state == "F5":
        if reason == "ok":
            return "F3"
        elif reason == "fail":
            return "D2"

    if state == "D2":
        if reason == "repair":
            return "F1"

    if state == "D1":
        if reason == "refused":
            return "A4"

    if state == "A4":
        if reason == "resolve":
            return "F2"

    if state == "F3":
        if reason == "stop":
            return "A2"

    if state == "A2":
        if reason == "new_request":
            return "A1"

    return None

