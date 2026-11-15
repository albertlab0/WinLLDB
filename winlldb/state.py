class State:
    def __init__(self):
        self.next_d = None
        self.last_d = "b"
        self.next_u = None
        self.source_mode = True


_states = {}


def get(ctx):
    key = (ctx.debugger.GetID(), ctx.debugger.GetIndexOfTarget(ctx.target))
    st = _states.get(key)
    if st is None:
        st = _states[key] = State()
    return st
