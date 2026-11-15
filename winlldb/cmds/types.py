import fnmatch

import lldb

from .. import args, fmt
from ..registry import WinDbgError, command

G = "Types"
_RECORD = (lldb.eTypeClassStruct, lldb.eTypeClassUnion, lldb.eTypeClassClass)
_SIGNED = {lldb.eBasicTypeShort, lldb.eBasicTypeInt, lldb.eBasicTypeLong, lldb.eBasicTypeLongLong,
           lldb.eBasicTypeInt128}
_UNSIGNED = {lldb.eBasicTypeUnsignedShort, lldb.eBasicTypeUnsignedInt, lldb.eBasicTypeUnsignedLong,
             lldb.eBasicTypeUnsignedLongLong, lldb.eBasicTypeUnsignedInt128}
_NAMED = {
    lldb.eBasicTypeVoid: "Void",
    lldb.eBasicTypeChar: "Char",
    lldb.eBasicTypeSignedChar: "Char",
    lldb.eBasicTypeUnsignedChar: "UChar",
    lldb.eBasicTypeWChar: "Wchar",
    lldb.eBasicTypeSignedWChar: "Wchar",
    lldb.eBasicTypeUnsignedWChar: "Wchar",
    lldb.eBasicTypeChar16: "Wchar",
    lldb.eBasicTypeChar32: "Uint4B",
    lldb.eBasicTypeBool: "Bool",
    lldb.eBasicTypeFloat: "Float",
    lldb.eBasicTypeDouble: "Float",
    lldb.eBasicTypeLongDouble: "Float",
}
_CHARS = {lldb.eBasicTypeChar, lldb.eBasicTypeSignedChar, lldb.eBasicTypeUnsignedChar}
_WCHARS = {lldb.eBasicTypeWChar, lldb.eBasicTypeSignedWChar, lldb.eBasicTypeUnsignedWChar,
           lldb.eBasicTypeChar16}
NAME_WIDTH = 16


def is_record(t):
    return t.GetCanonicalType().GetTypeClass() in _RECORD


def _strip_tag(name):
    for tag in ("struct ", "union ", "class ", "enum "):
        if name.startswith(tag):
            return name[len(tag):]
    return name


def win_type_name(t, ptrsize):
    """WinDbg-style type name: Int4B, Ptr64 Char, [4] Uint2B, _MY_STRUCT, ..."""
    c = t.GetCanonicalType()
    if c.IsPointerType() or c.IsReferenceType():
        pointee = c.GetPointeeType() if c.IsPointerType() else c.GetDereferencedType()
        return "Ptr%d %s" % (ptrsize * 8, win_type_name(pointee, ptrsize))
    if c.IsArrayType():
        elem = c.GetArrayElementType()
        n = c.GetByteSize() // max(elem.GetByteSize(), 1)
        return "[%d] %s" % (n, win_type_name(elem, ptrsize))
    tc = c.GetTypeClass()
    if tc in _RECORD or tc == lldb.eTypeClassEnumeration:
        name = _strip_tag(c.GetName() or "")
        if not name or "anonymous" in name:
            name = _strip_tag(t.GetName() or "") or "<anonymous-tag>"
        return name
    if tc == lldb.eTypeClassFunction:
        return "Function"
    bt = c.GetBasicType()
    if bt in _NAMED:
        return _NAMED[bt]
    if bt in _SIGNED:
        return "Int%dB" % c.GetByteSize()
    if bt in _UNSIGNED:
        return "Uint%dB" % c.GetByteSize()
    return c.GetName() or "<unknown>"


class Member:
    def __init__(self, offset, name, type_, bits, index):
        self.offset = offset
        self.name = name
        self.type = type_
        self.bits = bits
        self.index = index


def members(t):
    c = t.GetCanonicalType()
    out = []
    idx = 0
    for i in range(c.GetNumberOfDirectBaseClasses()):
        b = c.GetDirectBaseClassAtIndex(i)
        out.append(Member(b.GetOffsetInBytes(), _strip_tag(b.GetType().GetName()), b.GetType(), None, idx))
        idx += 1
    for i in range(c.GetNumberOfFields()):
        f = c.GetFieldAtIndex(i)
        bits = None
        off = f.GetOffsetInBytes()
        if f.IsBitfield():
            unit = f.GetType().GetByteSize() or 4
            bitoff = f.GetOffsetInBits()
            off = (bitoff // (unit * 8)) * unit
            bits = (bitoff - off * 8, f.GetBitfieldSizeInBits())
        out.append(Member(off, f.GetName() or "__unnamed", f.GetType(), bits, idx))
        idx += 1
    return out


def _char_repr(v):
    c = chr(v) if 0 <= v < 0x110000 else "?"
    return c if v >= 0x20 and c.isprintable() else ""


def scalar_value(v, ptrsize, short=False):
    """WinDbg-style rendering of a non-record value."""
    if not v.IsValid() or v.GetError().Fail():
        return "<unavailable>" if short else "Memory read error"
    t = v.GetType()
    c = t.GetCanonicalType()
    if c.IsPointerType() or c.IsReferenceType():
        s = "0x" + fmt.addr(v.GetValueAsUnsigned(), ptrsize)
        if short:
            return s
        summary = v.GetSummary()
        if summary:
            return "%s  %s" % (s, summary)
        pointee = c.GetPointeeType() if c.IsPointerType() else c.GetDereferencedType()
        pc = pointee.GetCanonicalType()
        if pc.GetTypeClass() in _RECORD or pc.GetBasicType() == lldb.eBasicTypeVoid:
            return "%s %s" % (s, win_type_name(pointee, ptrsize))
        return s
    if c.IsArrayType():
        elem_bt = c.GetArrayElementType().GetCanonicalType().GetBasicType()
        n = c.GetByteSize() // max(c.GetArrayElementType().GetByteSize(), 1)
        summary = None if elem_bt == lldb.eBasicTypeUnsignedChar else v.GetSummary()
        if summary:
            return "[%d] %s" % (n, summary)
        first = v.GetChildAtIndex(0)
        if n and first.IsValid() and not is_record(first.GetType()):
            return "[%d] %s" % (n, scalar_value(first, ptrsize, short=True))
        return "[%d] %s" % (n, win_type_name(c.GetArrayElementType(), ptrsize))
    tc = c.GetTypeClass()
    if tc in _RECORD:
        return win_type_name(t, ptrsize)
    if tc == lldb.eTypeClassEnumeration:
        n = v.GetValueAsSigned()
        name = v.GetValue()
        return "0n%d ( %s )" % (n, name) if name and not name.lstrip("-").isdigit() else "0n%d" % n
    bt = c.GetBasicType()
    if bt in _CHARS:
        n = v.GetValueAsSigned() if bt != lldb.eBasicTypeUnsignedChar else v.GetValueAsUnsigned()
        prefix = "0x%x" % (n & 0xFF) if bt == lldb.eBasicTypeUnsignedChar else "%d" % n
        return "%s '%s'" % (prefix, _char_repr(n & 0xFF))
    if bt in _WCHARS:
        n = v.GetValueAsUnsigned()
        return "0x%x '%s'" % (n, _char_repr(n))
    if bt == lldb.eBasicTypeBool:
        return "%d" % v.GetValueAsUnsigned()
    if bt in (lldb.eBasicTypeFloat, lldb.eBasicTypeDouble, lldb.eBasicTypeLongDouble):
        return v.GetValue() or "?"
    if bt in _SIGNED:
        return "0n%d" % v.GetValueAsSigned()
    size = c.GetByteSize()
    n = v.GetValueAsUnsigned()
    if size == 8:
        return "0x" + fmt.addr(n, 8)
    return "0x%x" % n


def bitfield_value(v, nbits):
    return "0y" + format(v.GetValueAsUnsigned() & ((1 << nbits) - 1), "0%db" % nbits)


def _field_prefix(indent, m):
    return "%s+0x%03x %-*s : " % (" " * indent, m.offset, NAME_WIDTH, m.name)


def _match(paths, name):
    """paths: list of dotted field filters at this level; returns (matched, subpaths)."""
    if not paths:
        return True, []
    sub = []
    hit = False
    for p in paths:
        head, _, rest = p.partition(".")
        if head == name or fnmatch.fnmatchcase(name, head):
            hit = True
            if rest:
                sub.append(rest)
    return hit, sub


class Dumper:
    def __init__(self, ctx, depth, arrays):
        self.ctx = ctx
        self.ptrsize = ctx.ptrsize
        self.depth = depth
        self.arrays = arrays
        self.lines = []

    def layout(self, t, indent=3, level=0, paths=()):
        for m in members(t):
            hit, sub = _match(paths, m.name)
            if not hit:
                continue
            prefix = _field_prefix(indent, m)
            if m.bits:
                self.lines.append(prefix + "Pos %d, %d Bit%s" % (m.bits[0], m.bits[1], "s" if m.bits[1] != 1 else ""))
                continue
            self.lines.append(prefix + win_type_name(m.type, self.ptrsize))
            if is_record(m.type) and (level < self.depth or sub):
                self.layout(m.type, indent + 3, level + 1, sub)

    def values(self, value, indent=3, level=0, paths=()):
        value = value.GetNonSyntheticValue()
        for m in members(value.GetType()):
            hit, sub = _match(paths, m.name)
            if not hit:
                continue
            child = value.GetChildAtIndex(m.index)
            prefix = _field_prefix(indent, m)
            if m.bits:
                self.lines.append(prefix + bitfield_value(child, m.bits[1]))
                continue
            self.lines.append(prefix + scalar_value(child, self.ptrsize))
            if is_record(m.type) and (level < self.depth or sub):
                self.values(child, indent + 3, level + 1, sub)
            elif self.arrays and m.type.GetCanonicalType().IsArrayType():
                self.array(child, indent + 3, level)

    def array(self, value, indent, level):
        n = value.GetNumChildren()
        for i in range(min(n, self.arrays)):
            el = value.GetChildAtIndex(i)
            pad = " " * indent
            if is_record(el.GetType()):
                self.lines.append("%s[%02d] %s" % (pad, i, win_type_name(el.GetType(), self.ptrsize)))
                self.values(el, indent + 3, level + 1)
            else:
                self.lines.append("%s[%02d] %s" % (pad, i, scalar_value(el, self.ptrsize)))


def _type_module_name(ctx, t):
    get_module = getattr(t, "GetModule", None)
    m = get_module() if get_module else None
    if m is None or not m.IsValid():
        m = ctx.target.GetModuleAtIndex(0)
    return fmt.module_name(m)


def find_type(ctx, name):
    target = ctx.target
    if "!" in name:
        modname, tname = name.split("!", 1)
        for m in ctx.find_modules(modname):
            t = m.FindFirstType(tname)
            if t.IsValid():
                return t
        return None
    t = target.FindFirstType(name)
    return t if t.IsValid() else None


def find_variable(ctx, name):
    if ctx.live_process() is not None:
        v = ctx.frame.FindVariable(name)
        if v.IsValid():
            return v, True
    g = ctx.target.FindFirstGlobalVariable(name.split("!", 1)[-1])
    if g.IsValid():
        return g, False
    return None, False


def list_types(ctx, pattern):
    modpat, _, tpat = pattern.rpartition("!")
    seen = set()
    for m in ctx.target.module_iter():
        mname = fmt.module_name(m)
        if modpat and not fnmatch.fnmatch(mname.lower(), modpat.lower()):
            continue
        types = m.GetTypes(lldb.eTypeClassStruct | lldb.eTypeClassUnion | lldb.eTypeClassClass |
                           lldb.eTypeClassEnumeration | lldb.eTypeClassTypedef)
        for i in range(types.GetSize()):
            tn = types.GetTypeAtIndex(i).GetName() or ""
            key = (mname, tn)
            if tn and key not in seen and fnmatch.fnmatchcase(tn, tpat):
                seen.add(key)
                ctx.write("          %s!%s" % (mname, tn))


@command("dt", "dt [-r[N]] [-a[N]] [mod!]Type|var [addr] [field[.sub]...]",
         "Display type layout, or memory/variable as that type", G)
def cmd_dt(ctx, name, text):
    depth, arrays, pos = 0, 0, []
    for tok in args.split(text):
        if tok.startswith("-") and len(tok) > 1 and tok[1].isalpha():
            opt, val = tok[1].lower(), tok[2:]
            if opt == "r":
                depth = int(val) if val.isdigit() else 9
            elif opt == "a":
                arrays = int(val) if val.isdigit() else 0x100
            elif opt in ("b", "v", "o"):
                pass
            else:
                raise WinDbgError("Unknown dt option '%s'" % tok)
        else:
            pos.append(tok)
    if not pos:
        raise WinDbgError("Usage: dt [-r[N]] [-a[N]] [mod!]Type|var [addr] [fields]")
    what = pos[0]
    if "*" in what or "?" in what:
        list_types(ctx, what)
        return
    d = Dumper(ctx, depth, arrays)
    ps = ctx.ptrsize
    t = find_type(ctx, what)
    if t is not None:
        if len(pos) == 1:
            ctx.write("%s!%s" % (_type_module_name(ctx, t), win_type_name(t, ps)))
            d.layout(t)
        else:
            a = ctx.eval(pos[1])
            value = ctx.target.CreateValueFromAddress("dt", fmt.resolve(ctx.target, a), t)
            if not is_record(t):
                d.lines.append(scalar_value(value, ps))
            else:
                d.values(value, paths=pos[2:])
        ctx.write("\n".join(d.lines))
        return
    var, local = find_variable(ctx, what)
    if var is None:
        raise WinDbgError("Symbol %s not found." % what)
    vt = var.GetType()
    ctx.write("%s @ 0x%s Type %s" % ("Local var" if local else "Global var", fmt.addr(var.GetLoadAddress(), ps),
                                       win_type_name(vt, ps)))
    c = vt.GetCanonicalType()
    if c.IsPointerType() and is_record(c.GetPointeeType()):
        ctx.write("0x" + fmt.addr(var.GetValueAsUnsigned(), ps))
        d.values(var.Dereference(), paths=pos[1:])
    elif is_record(vt):
        d.values(var, paths=pos[1:])
    else:
        d.lines.append(scalar_value(var, ps))
    if d.lines:
        ctx.write("\n".join(d.lines))
