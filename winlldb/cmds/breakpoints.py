import re

import lldb

from .. import args, expr, fmt
from ..registry import WinDbgError, command

G = "Breakpoints"
_info = {}


def wid(bp):
    return bp.GetID() - 1


def _key(ctx, bp):
    return (ctx.debugger.GetID(), ctx.debugger.GetIndexOfTarget(ctx.target), bp.GetID())


def _glob_to_regex(pat):
    out = []
    for ch in pat:
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "^" + "".join(out) + "$"


def _split_commands(text):
    cmds, cur, quote = [], [], False
    for ch in text:
        if ch == '"':
            quote = not quote
        if ch == ";" and not quote:
            cmds.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    cmds.append("".join(cur).strip())
    return [c for c in cmds if c]


def _lldb_command(c):
    return "process continue" if c in ("g", "gc") else c


def _module_file(ctx, modname):
    mods = ctx.find_modules(modname)
    return mods[0].GetFileSpec().GetFilename() if mods else None


def _create(ctx, name, where):
    target = ctx.target
    if where.startswith("`") and where.endswith("`") and ":" in where:
        path, _, line = where.strip("`").rpartition(":")
        if not line.isdigit():
            raise WinDbgError("Bad source line '%s'" % where)
        return target.BreakpointCreateByLocation(path, int(line)), None
    if name == "bm":
        modpat, _, sympat = where.rpartition("!")
        modfile = _module_file(ctx, modpat) if modpat else None
        return target.BreakpointCreateByRegex(_glob_to_regex(sympat), modfile), None
    if expr.is_symbol_name(where):
        modname, _, sym = where.rpartition("!")
        modfile = _module_file(ctx, modname) if modname else None
        bp = target.BreakpointCreateByName(sym, modfile)
        note = None
        if bp.GetNumLocations() == 0:
            note = "Bp expression '%s' could not be resolved, adding deferred bp" % where
        return bp, note
    return target.BreakpointCreateByAddress(ctx.eval(where)), None


@command("bp", 'bp [/1] [/w "cond"] <addr|[mod!]sym|`file:line`> [passcount] ["cmd;cmd"]',
         "Set a breakpoint", G)
@command("bu", 'bu [/1] [/w "cond"] [mod!]sym [passcount] ["cmd;cmd"]', "Set a deferred breakpoint", G)
@command("bm", 'bm [/1] [mod!]pattern* ["cmd;cmd"]', "Set breakpoints on all symbols matching a pattern", G)
def cmd_bp(ctx, name, text):
    toks = args.split(text)
    oneshot, cond, cmds, pos = False, None, None, []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "/1":
            oneshot = True
        elif t.lower() == "/w":
            if i + 1 >= len(toks):
                raise WinDbgError("/w requires a condition")
            i += 1
            cond = args.unquote(toks[i])
        elif t.startswith("/"):
            raise WinDbgError("Unsupported option '%s'" % t)
        elif t.startswith('"'):
            cmds = args.unquote(t)
        else:
            pos.append(t)
        i += 1
    if not pos:
        raise WinDbgError("Usage: %s <address|symbol>" % name)
    where = pos[0]
    bp, note = _create(ctx, name, where)
    if not bp.IsValid():
        raise WinDbgError("Unable to set breakpoint at '%s'" % where)
    if note:
        ctx.write(note)
    if oneshot:
        bp.SetOneShot(True)
    if cond:
        bp.SetCondition(cond)
    if len(pos) > 1:
        bp.SetIgnoreCount(max(ctx.eval(pos[1]) - 1, 0))
    if cmds:
        sl = lldb.SBStringList()
        for c in _split_commands(cmds):
            sl.AppendString(_lldb_command(c))
        bp.SetCommandLineCommands(sl)
    _info[_key(ctx, bp)] = (where, cmds)
    if name == "bm":
        for j in range(bp.GetNumLocations()):
            loc = bp.GetLocationAtIndex(j)
            a = fmt.load_addr(loc.GetAddress(), ctx.target)
            ctx.write('%3d: %s @!"%s"' % (wid(bp), fmt.addr(a, ctx.ptrsize), fmt.symbolize(ctx.target, a) or "?"))


@command("bl", "bl", "List breakpoints", G)
def cmd_bl(ctx, name, text):
    target, ps = ctx.target, ctx.ptrsize
    blank = " " * len(fmt.addr(0, ps))
    for bp in target.breakpoint_iter():
        where, cmds = _info.get(_key(ctx, bp), (None, None))
        flags = "e" if bp.IsEnabled() else "d"
        passes = bp.GetIgnoreCount() + 1
        n = bp.GetNumLocations()
        suffix = ' "%s"' % cmds if cmds else ""
        if bp.GetCondition():
            suffix += " /w \"%s\"" % bp.GetCondition()
        if n == 0 or bp.GetLocationAtIndex(0).GetLoadAddress() == fmt.INVALID:
            ctx.write("%2d %-2s %s     %04x (%04x)  0:**** (%s)%s" % (
                wid(bp), flags + "u", blank, passes, passes, where or "unresolved", suffix))
            continue
        for j in range(n):
            loc = bp.GetLocationAtIndex(j)
            a = loc.GetLoadAddress()
            sym = fmt.symbolize(target, a) or ""
            if j == 0:
                ctx.write("%2d %-2s %s     %04x (%04x)  0:**** %s%s" % (
                    wid(bp), flags, fmt.addr(a, ps), passes, passes, sym, suffix))
            else:
                ctx.write("   %-2s %s                    %s" % ("e" if loc.IsEnabled() else "d", fmt.addr(a, ps), sym))


def parse_ids(ctx, text):
    """Returns a list of WinDbg breakpoint ids, or None for '*'."""
    text = text.strip()
    if not text:
        raise WinDbgError("Breakpoint id required (or *)")
    if text == "*":
        return None
    ids = []
    for part in re.split(r"[\s,]+", text):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise WinDbgError("Bad breakpoint id '%s'" % part)
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        ids.extend(range(lo, hi + 1))
    return ids


@command("bc", "bc <id...|*>", "Clear (delete) breakpoints", G)
@command("bd", "bd <id...|*>", "Disable breakpoints", G)
@command("be", "be <id...|*>", "Enable breakpoints", G)
def cmd_bcde(ctx, name, text):
    target = ctx.target
    ids = parse_ids(ctx, text)
    if ids is None:
        {"bc": target.DeleteAllBreakpoints, "bd": target.DisableAllBreakpoints,
         "be": target.EnableAllBreakpoints}[name]()
        return
    for i in ids:
        bp = target.FindBreakpointByID(i + 1)
        if not bp.IsValid():
            ctx.write("Breakpoint %d not found" % i)
            continue
        if name == "bc":
            _info.pop(_key(ctx, bp), None)
            target.BreakpointDelete(bp.GetID())
        else:
            bp.SetEnabled(name == "be")
