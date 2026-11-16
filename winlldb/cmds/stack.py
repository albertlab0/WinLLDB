import re

import lldb

from .. import args, fmt
from ..registry import WinDbgError, command
from .types import scalar_value

G = "Stack & threads"
_KFLAGS = re.compile(r"^k([bpvnc]*)$")


def frame_site(ctx, frame, params=False):
    target = ctx.target
    pc = frame.GetPC()
    site = fmt.symbolize(target, pc) or fmt.addr(pc, ctx.ptrsize)
    if frame.IsInlined() or params:
        func = frame.GetFunctionName() or ""
        mod = fmt.module_name(frame.GetModule())
        fname = fmt.strip_params(func) or site.split("+")[0]
        if "!" not in fname and frame.GetModule().IsValid():
            fname = "%s!%s" % (mod, fname)
        off = ""
        sym = frame.GetSymbol()
        if sym.IsValid():
            delta = pc - fmt.load_addr(sym.GetStartAddress(), target)
            off = "+0x%x" % delta if delta > 0 else ""
        if params:
            fname += "(%s)" % (", ".join(
                "%s %s = %s" % (v.GetType().GetName(), v.GetName(), scalar_value(v, ctx.ptrsize, short=True))
                for v in frame.GetVariables(True, False, False, True)) or "void")
        site = fname + off
    le = frame.GetLineEntry()
    if le.IsValid() and le.GetLine():
        site += " [%s @ %d]" % (le.GetFileSpec().fullpath, le.GetLine())
    return site


def _stack_args(ctx, frame):
    vals = [v.GetValueAsUnsigned() for v in frame.GetVariables(True, False, False, True)][:4]
    if not vals:
        sp = frame.GetSP()
        vals = []
        for i in range(4):
            try:
                vals.append(ctx.read_uint(sp + (i + 1) * ctx.ptrsize, ctx.ptrsize))
            except WinDbgError:
                vals.append(0)
    return " ".join(fmt.addr(v, ctx.ptrsize) for v in vals + [0] * (4 - len(vals)))


def backtrace(ctx, thread, flags, limit=None):
    ps = ctx.ptrsize
    w = len(fmt.addr(0, ps))
    with_args = "b" in flags or "v" in flags
    params = "p" in flags
    only_site = "c" in flags
    head = " # "
    if only_site:
        ctx.write(head + "Call Site")
    elif with_args:
        ctx.write(head + "%-*s %-*s : %-*s : Call Site" % (w, "Child-SP", w + 4, "RetAddr", w * 4 + 3, "Args to Child"))
    else:
        ctx.write(head + "%-*s %-*s Call Site" % (w, "Child-SP", w + 4, "RetAddr"))
    n = thread.GetNumFrames()
    if limit is not None:
        n = min(n, limit)
    for i in range(n):
        f = thread.GetFrameAtIndex(i)
        nxt = thread.GetFrameAtIndex(i + 1)
        ret = nxt.GetPC() if nxt.IsValid() else 0
        num = "%02x " % i
        site = frame_site(ctx, f, params)
        if only_site:
            ctx.write(num + site)
        elif with_args:
            ctx.write("%s%s %s     : %s : %s" % (num, fmt.addr(f.GetSP(), ps), fmt.addr(ret, ps),
                                                _stack_args(ctx, f), site))
        else:
            ctx.write("%s%s %s     %s" % (num, fmt.addr(f.GetSP(), ps), fmt.addr(ret, ps), site))


def _k(ctx, name, text):
    flags = _KFLAGS.match(name).group(1)
    toks = args.split(text)
    limit = ctx.eval(toks[0]) if toks else None
    backtrace(ctx, ctx.thread, flags, limit)


# Frame numbers are always shown (as in current WinDbg); the n variants are kept for muscle memory.
for _name, _summary in [("k", "Stack backtrace"), ("kn", "Same as k"),
                        ("kb", "Stack backtrace with first args"), ("kv", "Same as kb"),
                        ("kp", "Stack backtrace with full parameters"), ("kc", "Call sites only"),
                        ("kbn", "Same as kb"), ("kpn", "Same as kp"), ("kvn", "Same as kv")]:
    command(_name, "%s [frames]" % _name, _summary, G)(_k)


@command(".frame", ".frame [/r] [N]", "Show or select the current frame (/r: also show registers)", G)
def cmd_frame(ctx, name, text):
    toks = args.split(text)
    regs = any(t.lower() == "/r" for t in toks)
    toks = [t for t in toks if not t.startswith("/")]
    thread = ctx.thread
    if toks:
        n = ctx.eval(toks[0])
        if n >= thread.GetNumFrames():
            raise WinDbgError("Frame %x out of range" % n)
        thread.SetSelectedFrame(n)
    f = thread.GetSelectedFrame()
    nxt = thread.GetFrameAtIndex(f.GetFrameID() + 1)
    ps = ctx.ptrsize
    ctx.write("%02x %s %s     %s" % (f.GetFrameID(), fmt.addr(f.GetSP(), ps),
                                      fmt.addr(nxt.GetPC() if nxt.IsValid() else 0, ps), frame_site(ctx, f)))
    if regs:
        from .registers import show_all
        show_all(ctx, f)


def _is_event(t):
    return t.GetStopReason() not in (lldb.eStopReasonInvalid, lldb.eStopReasonNone)


def _thread_line(ctx, i, t, current):
    p = ctx.process
    mark = "." if t.GetThreadID() == current else ("#" if _is_event(t) else " ")
    name = t.GetName() or ""
    return '%s %2d  Id: %x.%x Suspend: %d Unfrozen%s' % (
        mark, i, p.GetProcessID(), t.GetThreadID(), 1 if t.IsSuspended() else 0,
        ' "%s"' % name if name else "")


@command("~", "~ [N|*] [s | command]", "List threads, select (~ Ns), or run a command per thread (~ * k)", G)
def cmd_threads(ctx, name, text):
    p = ctx.process
    threads = [p.GetThreadAtIndex(i) for i in range(p.GetNumThreads())]
    current = p.GetSelectedThread().GetThreadID()
    if not text:
        for i, t in enumerate(threads):
            ctx.write(_thread_line(ctx, i, t, current))
        return
    m = re.match(r"^(\*|\.|#|[0-9a-fA-F]+)\s*(.*)$", text)
    if not m:
        raise WinDbgError("Syntax: ~ [N|*] [s | command]")
    sel, rest = m.group(1), m.group(2).strip()
    if sel == "*":
        chosen = list(enumerate(threads))
    elif sel == ".":
        chosen = [(i, t) for i, t in enumerate(threads) if t.GetThreadID() == current]
    elif sel == "#":
        chosen = [(i, t) for i, t in enumerate(threads) if _is_event(t)][:1]
    else:
        n = int(sel, 16)
        if n >= len(threads):
            raise WinDbgError("Illegal thread error in '~%s'" % sel)
        chosen = [(n, threads[n])]
    if rest == "s":
        if len(chosen) != 1:
            raise WinDbgError("Select exactly one thread")
        p.SetSelectedThread(chosen[0][1])
        f = chosen[0][1].GetSelectedFrame()
        ctx.write(frame_site(ctx, f))
        return
    if not rest:
        for i, t in chosen:
            ctx.write(_thread_line(ctx, i, t, current))
        return
    orig = p.GetSelectedThread()
    try:
        for i, t in chosen:
            ctx.write("")
            ctx.write(_thread_line(ctx, i, t, current))
            p.SetSelectedThread(t)
            ctx.run(rest)
    finally:
        p.SetSelectedThread(orig)
