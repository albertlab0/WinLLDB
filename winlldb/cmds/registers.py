import lldb

from .. import fmt
from ..registry import WinDbgError, command
from . import disasm

G = "Registers"
_X64_ROWS = [("rax", "rbx", "rcx"), ("rdx", "rsi", "rdi"), ("rip", "rsp", "rbp"),
             ("r8", "r9", "r10"), ("r11", "r12", "r13"), ("r14", "r15")]
_X86_ROWS = [("eax", "ebx", "ecx", "edx", "esi", "edi"), ("eip", "esp", "ebp")]
_SEGS = ("cs", "ss", "ds", "es", "fs", "gs")
# (bit, set, clear) in WinDbg display order
_FLAGS = [(11, "ov", "nv"), (10, "dn", "up"), (9, "ei", "di"), (7, "ng", "pl"),
          (6, "zr", "nz"), (4, "ac", "na"), (2, "pe", "po"), (0, "cy", "nc")]
_FLAG_BITS = {"of": 11, "df": 10, "if": 9, "sf": 7, "zf": 6, "af": 4, "pf": 2, "cf": 0, "tf": 8}


def _reg(frame, name):
    r = frame.FindRegister(name)
    return r if r.IsValid() and r.GetValue() is not None else None


def _u(frame, name):
    r = _reg(frame, name)
    return r.GetValueAsUnsigned() if r else 0


def flags_text(efl):
    return " ".join(s if efl & (1 << bit) else c for bit, s, c in _FLAGS)


def _current_instruction(ctx, frame):
    pc = frame.GetPC()
    insts = disasm.read_insts(ctx, pc, 1)
    sym = fmt.symbolize(ctx.target, pc)
    if sym:
        ctx.write(sym + ":")
    if insts:
        ctx.write(disasm.format_inst(ctx, insts[0]))


def show_all(ctx, frame):
    arch = ctx.arch
    if arch.startswith("x86_64"):
        for row in _X64_ROWS:
            ctx.write(" ".join("%3s=%016x" % (r, _u(frame, r)) for r in row))
        efl = _u(frame, "rflags")
        ctx.write("iopl=%d         %s" % ((efl >> 12) & 3, flags_text(efl)))
        segs = "  ".join("%s=%04x" % (s, _u(frame, s)) for s in _SEGS)
        ctx.write("%s             efl=%08x" % (segs, efl))
    elif ctx.is_x86():
        for row in _X86_ROWS:
            ctx.write(" ".join("%s=%08x" % (r, _u(frame, r)) for r in row))
        efl = _u(frame, "eflags")
        ctx.write("iopl=%d         %s" % ((efl >> 12) & 3, flags_text(efl)))
        segs = "  ".join("%s=%04x" % (s, _u(frame, s)) for s in _SEGS)
        ctx.write("%s             efl=%08x" % (segs, efl))
    else:
        regsets = frame.GetRegisters()
        gpr = regsets.GetValueAtIndex(0) if regsets.GetSize() else None
        if gpr is None:
            raise WinDbgError("No registers available")
        cells = []
        for i in range(gpr.GetNumChildren()):
            r = gpr.GetChildAtIndex(i)
            if r.GetByteSize() <= 8:
                cells.append("%4s=%0*x" % (r.GetName(), r.GetByteSize() * 2, r.GetValueAsUnsigned()))
        for i in range(0, len(cells), 4):
            ctx.write(" ".join(cells[i:i + 4]))
    _current_instruction(ctx, frame)


def _flag_reg(ctx, frame):
    return "rflags" if ctx.arch.startswith("x86_64") else "eflags"


def _show_one(ctx, frame, name):
    low = name.lower()
    if ctx.is_x86() and low in _FLAG_BITS:
        return "%s=%d" % (low, (_u(frame, _flag_reg(ctx, frame)) >> _FLAG_BITS[low]) & 1)
    r = _reg(frame, low)
    if r is None:
        raise WinDbgError("Bad register error at '%s'" % name)
    size = r.GetByteSize()
    if size <= 8:
        return "%s=%0*x" % (low, size * 2, r.GetValueAsUnsigned())
    return "%s=%s" % (low, r.GetValue())


def _set(ctx, frame, name, text):
    low = name.lower()
    value = ctx.eval(text)
    if ctx.is_x86() and low in _FLAG_BITS:
        fr = _flag_reg(ctx, frame)
        efl = _u(frame, fr)
        bit = 1 << _FLAG_BITS[low]
        efl = (efl | bit) if value else (efl & ~bit)
        low, value = fr, efl
    r = _reg(frame, low)
    if r is None:
        raise WinDbgError("Bad register error at '%s'" % name)
    err = lldb.SBError()
    if not r.SetValueFromCString("0x%x" % value, err) or err.Fail():
        raise WinDbgError("Unable to set %s: %s" % (name, err.GetCString() or "unknown error"))


@command("r", "r [reg[=expr]][, reg[=expr]...]", "Display or modify registers", G)
def cmd_r(ctx, name, text):
    frame = ctx.frame
    if not text:
        show_all(ctx, frame)
        return
    shown = []
    for item in (s.strip() for s in text.split(",")):
        if not item:
            continue
        if "=" in item:
            reg, _, val = item.partition("=")
            _set(ctx, frame, reg.strip().lstrip("@"), val.strip())
        else:
            shown.append(_show_one(ctx, frame, item.lstrip("@")))
    if shown:
        ctx.write(" ".join(shown))
