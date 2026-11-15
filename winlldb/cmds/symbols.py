import fnmatch
import os
import re

import lldb

from .. import args, fmt
from ..registry import WinDbgError, command
from .types import scalar_value

G = "Symbols & search"
_CODE = (lldb.eSymbolTypeCode, lldb.eSymbolTypeResolver)
_DATA = (lldb.eSymbolTypeData,)
_SEARCH_CHUNK = 0x100000
_MAX_HITS = 4096


# ---------------------------------------------------------------- lm
def _symbol_status(m):
    if m.GetNumCompileUnits() > 0:
        return "(dwarf symbols)"
    if m.GetNumSymbols() > 0:
        return "(export symbols)"
    return "(no symbols)"


@command("lm", "lm [v] [f] [m pattern]", "List loaded modules", G)
@command("lmv", "lmv [m pattern]", "List modules, verbose", G)
@command("lmm", "lmm pattern", "List modules matching pattern", G)
@command("lmf", "lmf [m pattern]", "List modules with full image paths", G)
@command("lmvm", "lmvm pattern", "Verbose info for modules matching pattern", G)
def cmd_lm(ctx, name, text):
    flags = set(name[2:])
    toks = args.split(text)
    pattern = None
    expect_pattern = "m" in flags
    for t in toks:
        if expect_pattern:
            pattern, expect_pattern = t, False
        elif re.fullmatch(r"[vfmMol]+", t):
            flags |= set(t.lower())
            expect_pattern = "m" in t.lower()
        else:
            pattern = t
    target, ps = ctx.target, ctx.ptrsize
    w = len(fmt.addr(0, ps))
    ctx.write("%-*s %-*s   module name" % (w, "start", w, "end"))
    for m in target.module_iter():
        mname = fmt.module_name(m)
        if pattern and not fnmatch.fnmatch(mname.lower(), pattern.lower()):
            continue
        lo, hi = fmt.module_range(target, m)
        path = m.GetFileSpec().fullpath or ""
        symfile = m.GetSymbolFileSpec().fullpath or path
        info = path if "f" in flags else "%-18s %s" % (_symbol_status(m), symfile)
        ctx.write("%s %s   %-10s %s" % (fmt.addr(lo or 0, ps), fmt.addr(hi or 0, ps), mname, info))
        if "v" in flags:
            ctx.write("    Loaded symbol image file: %s" % symfile)
            ctx.write("    Image path: %s" % path)
            ctx.write("    Image name: %s" % (m.GetFileSpec().GetFilename() or ""))
            ctx.write("    UUID:       %s" % (m.GetUUIDString() or ""))
            ctx.write("    Triple:     %s" % (m.GetTriple() or ""))
            ctx.write("    Symbols:    %s, %d symbols, %d compile units" % (
                _symbol_status(m), m.GetNumSymbols(), m.GetNumCompileUnits()))


# ---------------------------------------------------------------- x / ln
def _module_symbols(ctx, m, kinds=_CODE + _DATA):
    target = ctx.target
    seen = set()
    out = []
    for i in range(m.GetNumSymbols()):
        s = m.GetSymbolAtIndex(i)
        if s.GetType() not in kinds:
            continue
        a = fmt.load_addr(s.GetStartAddress(), target)
        if a == fmt.INVALID:
            continue
        name = fmt.symbol_name(s)
        if (a, name) in seen:
            continue
        seen.add((a, name))
        out.append((a, name, s))
    out.sort(key=lambda e: e[0])
    return out


def _signature(ctx, sym):
    func = sym.GetStartAddress().GetFunction()
    if not func.IsValid():
        return "(<no parameter info>)"
    argtypes = func.GetType().GetFunctionArgumentTypes()
    return "(%s)" % ", ".join(argtypes.GetTypeAtIndex(i).GetName() for i in range(argtypes.GetSize()))


def _data_value(ctx, m, name):
    vals = m.FindGlobalVariables(ctx.target, name, 1)
    if vals.GetSize():
        return "= " + scalar_value(vals.GetValueAtIndex(0), ctx.ptrsize)
    return "= <no type information>"


@command("x", "x [/f|/d] [mod!]pattern", "Examine symbols (no '!': local variables)", G)
def cmd_x(ctx, name, text):
    toks = args.split(text)
    opts = {t.lower() for t in toks if t.startswith("/")}
    toks = [t for t in toks if not t.startswith("/")]
    pattern = toks[0] if toks else "*"
    ps = ctx.ptrsize
    if "!" not in pattern:
        for v in ctx.frame.GetVariables(True, True, False, True):
            if fnmatch.fnmatch(v.GetName(), pattern):
                ctx.write("%s %s = %s" % (fmt.addr(v.GetLoadAddress(), ps), v.GetName(), scalar_value(v, ps)))
        return
    modpat, _, sympat = pattern.partition("!")
    kinds = _CODE if "/f" in opts else _DATA if "/d" in opts else _CODE + _DATA
    regex = re.compile(fnmatch.translate(sympat), re.I)
    hits = 0
    for m in ctx.target.module_iter():
        mname = fmt.module_name(m)
        if not fnmatch.fnmatch(mname.lower(), modpat.lower()):
            continue
        for a, sname, s in _module_symbols(ctx, m, kinds):
            if not regex.match(sname):
                continue
            detail = _signature(ctx, s) if s.GetType() in _CODE else _data_value(ctx, m, sname)
            ctx.write("%s %s!%s %s" % (fmt.addr(a, ps), mname, sname, detail))
            hits += 1
            if hits >= _MAX_HITS:
                ctx.write("... output truncated at %d symbols" % _MAX_HITS)
                return


@command("ln", "ln [addr]", "List nearest symbols", G)
def cmd_ln(ctx, name, text):
    a = ctx.eval(text) if text else ctx.frame.GetPC()
    target, ps = ctx.target, ctx.ptrsize
    m = fmt.resolve(target, a).GetModule()
    if not m.IsValid():
        ctx.write("No symbols found near %s" % fmt.addr(a, ps))
        return
    mname = fmt.module_name(m)
    syms = _module_symbols(ctx, m)
    prev = [e for e in syms if e[0] <= a]
    nxt = [e for e in syms if e[0] > a]
    left = "(%s)   %s!%s%s" % (fmt.addr(prev[-1][0], ps), mname, prev[-1][1],
                               "+0x%x" % (a - prev[-1][0]) if a > prev[-1][0] else "") if prev else ""
    right = "(%s)   %s!%s" % (fmt.addr(nxt[0][0], ps), mname, nxt[0][1]) if nxt else ""
    ctx.write("%s   |  %s" % (left, right))
    exact = [e for e in syms if e[0] == a]
    if exact:
        ctx.write("Exact matches:")
        for _, sname, s in exact:
            detail = _signature(ctx, s) if s.GetType() in _CODE else ""
            ctx.write("    %s!%s %s" % (mname, sname, detail))


# ---------------------------------------------------------------- s
def _pattern(ctx, kind, toks):
    if not toks:
        raise WinDbgError("Search pattern required")
    if kind in ("a", "u"):
        text = args.unquote(" ".join(toks))
        return text.encode("utf-16-le" if kind == "u" else "latin-1")
    size = {"b": 1, "w": 2, "d": 4, "q": 8}[kind]
    out = b""
    for t in toks:
        v = ctx.eval(t)
        if v >= 1 << (size * 8):
            raise WinDbgError("Value %s does not fit in %d bytes" % (t, size))
        out += v.to_bytes(size, ctx.byteorder)
    return out


def _readable_spans(ctx, start, end):
    """Yield (addr, size) spans of readable memory in [start, end)."""
    p = ctx.process
    a = start
    while a < end:
        info = lldb.SBMemoryRegionInfo()
        if p.GetMemoryRegionInfo(a, info).Fail():
            yield a, end - a
            return
        rend = min(info.GetRegionEnd(), end)
        if rend <= a:
            yield a, end - a
            return
        if info.IsReadable():
            yield a, rend - a
        a = rend


def _show_hit(ctx, kind, a):
    if kind in ("b", "a", "u"):
        ctx.write(fmt.hexdump_line(a, ctx.read_partial(a, 16), ctx.ptrsize))
    else:
        from .memory import cmd_display
        cmd_display(ctx, "d" + kind, "%x L%x" % (a, 16 // {"w": 2, "d": 4, "q": 8}[kind]))


@command("s", "s [-b|-w|-d|-q|-a|-u] <start> <L len | end> <pattern>", "Search memory", G)
def cmd_s(ctx, name, text):
    toks = args.split(text)
    kind = "b"
    if toks and re.fullmatch(r"-[bwdqau]", toks[0]):
        kind = toks.pop(0)[1]
    elem = {"b": 1, "a": 1, "w": 2, "u": 2, "d": 4, "q": 8}[kind]
    rng = args.parse_range(ctx, toks, None, elem)
    if rng.start is None or not rng.explicit:
        raise WinDbgError("Range required: s -%s <start> L<len> <pattern>" % kind)
    pat = _pattern(ctx, kind, rng.rest)
    end = rng.start + rng.count * elem
    align = elem if kind in ("w", "d", "q") else 1
    hits = 0
    for base, size in _readable_spans(ctx, rng.start, end):
        off = 0
        while off < size:
            n = min(_SEARCH_CHUNK, size - off)
            data = bytes(b if b is not None else 0 for b in
                         ctx.read_partial(base + off, min(n + len(pat) - 1, size - off)))
            i = data.find(pat)
            while 0 <= i < n:
                a = base + off + i
                if a % align == 0:
                    _show_hit(ctx, kind, a)
                    hits += 1
                    if hits >= _MAX_HITS:
                        ctx.write("... search stopped after %d hits" % _MAX_HITS)
                        return
                i = data.find(pat, i + 1)
            off += n


# ---------------------------------------------------------------- ? / ?? / dv
@command("?", "? <expr>", "Evaluate a MASM expression", G)
def cmd_eval(ctx, name, text):
    if not text:
        from .help import cmd_winhelp
        return cmd_winhelp(ctx, "winhelp", "")
    v = ctx.eval(text)
    signed = v - (1 << 64) if v >= 1 << 63 else v
    ctx.write("Evaluate expression: %d = %s" % (signed, fmt.addr(v, 8)))


@command("??", "?? <C expression>", "Evaluate a C/C++ expression (LLDB 'expression')", G)
def cmd_cexpr(ctx, name, text):
    if not text:
        raise WinDbgError("Expression required")
    ctx.run("expression -- " + text)


@command("dv", "dv [/t] [/V] [/i] [pattern]", "Display local variables", G)
def cmd_dv(ctx, name, text):
    toks = args.split(text)
    opts = {t for t in toks if t.startswith("/")}
    pats = [t for t in toks if not t.startswith("/")]
    pattern = pats[0] if pats else "*"
    frame, ps = ctx.frame, ctx.ptrsize
    variables = [v for v in frame.GetVariables(True, True, False, True) if fnmatch.fnmatch(v.GetName(), pattern)]
    width = max([len(v.GetName()) for v in variables] + [14])
    for v in variables:
        prefix = ""
        if "/i" in opts:
            prefix += "%-11s" % ("prv param" if v.GetValueType() == lldb.eValueTypeVariableArgument else "prv local")
        if "/V" in opts:
            prefix += "%s  " % fmt.addr(v.GetLoadAddress(), ps)
        tname = ("%s " % v.GetType().GetName()) if "/t" in opts else ""
        ctx.write("%s%s%*s = %s" % (prefix, tname, width if not tname else 0, v.GetName(), scalar_value(v, ps)))


# ---------------------------------------------------------------- .reload / .sympath
@command(".reload", ".reload [/f] [symbolfile]", "Add a symbol file (LLDB loads module symbols automatically)", G)
def cmd_reload(ctx, name, text):
    toks = [t for t in args.split(text) if not t.startswith("/")]
    if not toks:
        ctx.write("Reloading current modules")
        ctx.write("Note: LLDB loads symbols automatically; use '.reload <symbol file>' to add one explicitly.")
        return
    for t in toks:
        path = args.unquote(t)
        if os.path.exists(path):
            ctx.run('target symbols add "%s"' % path)
        else:
            mods = ctx.find_modules(path.split("=")[0])
            if not mods:
                raise WinDbgError("Module or symbol file '%s' not found" % path)
            ctx.run('target symbols add --shlib "%s"' % mods[0].GetFileSpec().fullpath)


@command(".sympath", ".sympath [+] [path]", "Show or set debug symbol search paths", G)
def cmd_sympath(ctx, name, text):
    text = text.strip()
    if text.startswith("+"):
        ctx.run('settings append target.debug-file-search-paths "%s"' % text[1:].strip())
    elif text:
        ctx.run('settings set target.debug-file-search-paths "%s"' % text)
    ctx.run("settings show target.debug-file-search-paths")
