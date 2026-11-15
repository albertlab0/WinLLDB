import lldb

from .. import fmt, state
from ..registry import WinDbgError, command

G = "Execution"
_STEP_LIMIT = 200000
_QUIET_STOPS = (lldb.eStopReasonNone, lldb.eStopReasonTrace, lldb.eStopReasonPlanComplete)


def _alive(ctx):
    p = ctx.target.GetProcess()
    return p.IsValid() and p.GetState() not in (lldb.eStateInvalid, lldb.eStateExited,
                                                 lldb.eStateDetached, lldb.eStateUnloaded)


@command("g", "g [addr]", "Go (continue); launches the target if not running; with addr: run to addr", G)
def cmd_g(ctx, name, text):
    target = ctx.target
    if not _alive(ctx):
        if text:
            raise WinDbgError("Process is not running")
        ctx.run("process launch")
        return
    temp = None
    if text:
        temp = target.BreakpointCreateByAddress(ctx.eval(text))
        temp.SetOneShot(True)
    try:
        ctx.run("process continue")
    finally:
        if temp is not None and target.FindBreakpointByID(temp.GetID()).IsValid():
            target.BreakpointDelete(temp.GetID())


@command("gu", "gu", "Go up: run until the current function returns", G)
def cmd_gu(ctx, name, text):
    ctx.run("thread step-out")


def _has_source(ctx):
    le = ctx.frame.GetLineEntry()
    return state.get(ctx).source_mode and le.IsValid() and le.GetLine() != 0


@command("p", "p [count]", "Step over (source line if available, else instruction)", G)
@command("t", "t [count]", "Trace / step into (source line if available, else instruction)", G)
def cmd_step(ctx, name, text):
    n = ctx.eval(text) if text else 1
    for _ in range(n):
        src = _has_source(ctx)
        if name == "p":
            ctx.run("thread step-over" if src else "thread step-inst-over")
        else:
            ctx.run("thread step-in" if src else "thread step-inst")
        if ctx.live_process() is None:
            break


@command("l+t", "l+t", "Source-mode stepping for p/t (default)", G)
@command("l-t", "l-t", "Instruction-mode stepping for p/t", G)
def cmd_source_mode(ctx, name, text):
    state.get(ctx).source_mode = name == "l+t"
    ctx.write("Source options are %s" % ("source stepping" if name == "l+t" else "assembly stepping"))


def _mnemonic(ctx):
    thread = ctx.thread
    pc = thread.GetFrameAtIndex(0).GetPC()
    lst = ctx.target.ReadInstructions(fmt.resolve(ctx.target, pc), 1)
    return (lst.GetInstructionAtIndex(0).GetMnemonic(ctx.target) or "") if lst.GetSize() else ""


def _step_until(ctx, over, pred):
    thread = ctx.thread
    was_async = ctx.debugger.GetAsync()
    ctx.debugger.SetAsync(False)
    try:
        for _ in range(_STEP_LIMIT):
            thread.StepInstruction(over)
            if ctx.live_process() is None or thread.GetStopReason() not in _QUIET_STOPS:
                break
            if pred(_mnemonic(ctx)):
                break
    finally:
        ctx.debugger.SetAsync(was_async)
    if ctx.live_process() is not None:
        ctx.run("process status")


@command("pt", "pt", "Step over until the next return instruction", G)
def cmd_pt(ctx, name, text):
    _step_until(ctx, True, lambda m: m.startswith("ret"))


@command("pc", "pc", "Step over until the next call instruction", G)
def cmd_pc(ctx, name, text):
    _step_until(ctx, True, lambda m: m.startswith("call") or m in ("bl", "blr"))


@command("tc", "tc", "Step into until the next call instruction", G)
def cmd_tc(ctx, name, text):
    _step_until(ctx, False, lambda m: m.startswith("call") or m in ("bl", "blr"))
