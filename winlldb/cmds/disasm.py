import re

import lldb

from .. import args, fmt, state
from ..registry import WinDbgError, command

G = "Disassembly"
_HEXIMM = re.compile(r"(?<![\w`])0x([0-9a-fA-F]+)\b")
_RIPREL = re.compile(r"\[rip([+-])0x([0-9a-fA-F]+)\]")
_PURE_ADDR = re.compile(r"^0x([0-9a-fA-F]+)$")


def flavor(ctx):
    return "intel" if ctx.is_x86() else None


def _list(lst):
    return [lst.GetInstructionAtIndex(i) for i in range(lst.GetSize())]


def read_insts(ctx, a, count):
    target = ctx.target
    sbaddr = fmt.resolve(target, a)
    fl = flavor(ctx)
    lst = target.ReadInstructions(sbaddr, count, fl) if fl else target.ReadInstructions(sbaddr, count)
    return _list(lst)


def inst_addr(ctx, inst):
    return fmt.load_addr(inst.GetAddress(), ctx.target)


def branch_target(ctx, inst):
    if not inst.DoesBranch():
        return None
    m = _PURE_ADDR.match((inst.GetOperands(ctx.target) or "").strip())
    return int(m.group(1), 16) if m else None


def _imm(m):
    v = int(m.group(1), 16)
    if v < 10:
        return str(v)
    s = "%X" % v
    return ("0" + s if s[0] in "ABCDEF" else s) + "h"


def win_operands(ctx, inst, a):
    target, ps = ctx.target, ctx.ptrsize
    bt = branch_target(ctx, inst)
    if bt is not None:
        sym = fmt.symbolize(target, bt)
        return "%s (%s)" % (sym, fmt.addr(bt, ps)) if sym else fmt.addr(bt, ps)
    ops = (inst.GetOperands(target) or "").strip()
    if not ctx.is_x86():
        return ops
    ops = ops.replace(", ", ",").replace(" + ", "+").replace(" - ", "-").replace(" * ", "*")

    def riprel(m):
        disp = int(m.group(2), 16)
        t = a + inst.GetByteSize() + (disp if m.group(1) == "+" else -disp)
        sym = fmt.symbolize(target, t)
        return "[%s (%s)]" % (sym, fmt.addr(t, ps)) if sym else "[%s]" % fmt.addr(t, ps)

    ops = _RIPREL.sub(riprel, ops)
    return _HEXIMM.sub(_imm, ops)


def format_inst(ctx, inst):
    target = ctx.target
    a = inst_addr(ctx, inst)
    err = lldb.SBError()
    raw = inst.GetData(target).ReadRawData(err, 0, inst.GetByteSize()) or b""
    mnem = inst.GetMnemonic(target) or ""
    line = "%s %-15s %-7s %s" % (fmt.addr(a, ctx.ptrsize), raw.hex(), mnem, win_operands(ctx, inst, a))
    return line.rstrip()


def render(ctx, insts, labels=()):
    target = ctx.target
    lines = []
    cur = object()
    for inst in insts:
        a = inst_addr(ctx, inst)
        start = fmt.symbol_start(target, a)
        if start != cur or start == a or a in labels:
            sym = fmt.symbolize(target, a)
            if sym:
                lines.append(sym + ":")
        cur = start
        lines.append(format_inst(ctx, inst))
    return lines


def _default_addr(ctx):
    st = state.get(ctx)
    return st.next_u if st.next_u is not None else ctx.frame.GetPC()


@command("u", "u [addr] [L count | end]", "Unassemble forward (default 8 instructions)", G)
def cmd_u(ctx, name, text):
    rng = args.parse_range(ctx, args.split(text), 8, None)
    if rng.rest:
        raise WinDbgError("Extra argument '%s'" % rng.rest[0])
    start = rng.start if rng.start is not None else _default_addr(ctx)
    if rng.end is not None:
        insts = [i for i in read_insts(ctx, start, min(rng.end - start + 1, 0x10000))
                 if inst_addr(ctx, i) <= rng.end]
    else:
        insts = read_insts(ctx, start, rng.count)
    if not insts:
        raise WinDbgError("Unable to read memory at %s" % fmt.addr(start, ctx.ptrsize))
    for line in render(ctx, insts):
        ctx.write(line)
    last = insts[-1]
    state.get(ctx).next_u = inst_addr(ctx, last) + last.GetByteSize()


def _decode_span(ctx, start, end):
    """Instructions decoded from start that end exactly at end, else None."""
    if start < 0 or start >= end:
        return None
    out = []
    for inst in read_insts(ctx, start, end - start):
        if inst_addr(ctx, inst) >= end:
            break
        out.append(inst)
    if out and inst_addr(ctx, out[-1]) + out[-1].GetByteSize() == end:
        return out
    return None


def _heuristic_back(ctx, t, n):
    best = []
    for back in range(n * 15, 0, -1):
        span = _decode_span(ctx, t - back, t)
        if span and len(span) >= n:
            return span[-n:]
        if span and len(span) > len(best):
            best = span
    return best


def back_insts(ctx, t, n):
    if not ctx.is_x86():
        width = 4 if ctx.arch.startswith(("aarch64", "arm64")) else 2
        return read_insts(ctx, t - width * n, n)
    target = ctx.target
    sbaddr = fmt.resolve(target, t - 1)
    fstart = None
    for obj in (sbaddr.GetFunction(), sbaddr.GetSymbol()):
        if obj.IsValid():
            fstart = fmt.load_addr(obj.GetStartAddress(), target)
            break
    if fstart is not None and 0 < t - fstart <= 0x4000:
        span = _decode_span(ctx, fstart, t)
        if span:
            if len(span) >= n:
                return span[-n:]
            return _heuristic_back(ctx, fstart, n - len(span)) + span
    return _heuristic_back(ctx, t, n)


@command("ub", "ub [addr] [L count]", "Unassemble backward (default 8 instructions)", G)
def cmd_ub(ctx, name, text):
    rng = args.parse_range(ctx, args.split(text), 8, None, allow_end=False)
    if rng.rest:
        raise WinDbgError("Extra argument '%s'" % rng.rest[0])
    t = rng.start if rng.start is not None else _default_addr(ctx)
    insts = back_insts(ctx, t, rng.count)
    if not insts:
        raise WinDbgError("Unable to disassemble backward from %s" % fmt.addr(t, ctx.ptrsize))
    for line in render(ctx, insts):
        ctx.write(line)
    state.get(ctx).next_u = t


def function_insts(ctx, a):
    target = ctx.target
    sbaddr = fmt.resolve(target, a)
    fl = flavor(ctx)
    for obj in (sbaddr.GetFunction(), sbaddr.GetSymbol()):
        if obj.IsValid():
            lst = obj.GetInstructions(target, fl) if fl else obj.GetInstructions(target)
            insts = _list(lst)
            if insts:
                return fmt.load_addr(obj.GetStartAddress(), target), insts
    raise WinDbgError("No code found, aborting")


@command("uf", "uf [/c] [addr]", "Unassemble the whole function (/c: calls only)", G)
def cmd_uf(ctx, name, text):
    toks = args.split(text)
    calls = any(t.lower() == "/c" for t in toks)
    toks = [t for t in toks if not t.startswith("/")]
    a = ctx.eval(toks[0]) if toks else ctx.frame.GetPC()
    start, insts = function_insts(ctx, a)
    target, ps = ctx.target, ctx.ptrsize
    if calls:
        ctx.write("%s (%s)" % (fmt.symbolize(target, start), fmt.addr(start, ps)))
        for inst in insts:
            if (inst.GetMnemonic(target) or "").startswith("call"):
                ia = inst_addr(ctx, inst)
                ctx.write("  %s (%s):" % (fmt.symbolize(target, ia), fmt.addr(ia, ps)))
                ctx.write("    call to %s" % win_operands(ctx, inst, ia))
        return
    addrs = {inst_addr(ctx, i) for i in insts}
    labels = {bt for bt in (branch_target(ctx, i) for i in insts) if bt in addrs}
    for line in render(ctx, insts, labels):
        ctx.write(line)
