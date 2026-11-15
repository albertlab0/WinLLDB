import lldb

MASK64 = (1 << 64) - 1
INVALID = lldb.LLDB_INVALID_ADDRESS


def addr(v, ptrsize=8):
    v &= MASK64
    if ptrsize == 4:
        return "%08x" % (v & 0xFFFFFFFF)
    return "%08x`%08x" % (v >> 32, v & 0xFFFFFFFF)


def resolve(target, a):
    """SBAddress for a load address, falling back to a file address before launch."""
    sbaddr = target.ResolveLoadAddress(a)
    if not sbaddr.GetSection().IsValid():
        file_addr = target.ResolveFileAddress(a)
        if file_addr.GetSection().IsValid():
            return file_addr
    return sbaddr


def load_addr(sbaddr, target):
    a = sbaddr.GetLoadAddress(target)
    if a == INVALID:
        a = sbaddr.GetFileAddress()
    return a


def module_name(module):
    if module is None or not module.IsValid():
        return "<unknown>"
    fn = module.GetFileSpec().GetFilename() or "<unknown>"
    return fn.split(".")[0] or fn


def module_range(target, module):
    lo = hi = None
    loaded = target.GetProcess().IsValid()
    for i in range(module.GetNumSections()):
        s = module.GetSectionAtIndex(i)
        size = s.GetByteSize()
        if not size or s.GetName() == "__PAGEZERO" or not s.GetPermissions():
            continue
        la = s.GetLoadAddress(target)
        if la == INVALID:
            if loaded:
                continue
            la = s.GetFileAddress()
            if la == INVALID:
                continue
        lo = la if lo is None else min(lo, la)
        hi = la + size if hi is None else max(hi, la + size)
    return lo, hi


def strip_params(name):
    if not name:
        return name
    if name.endswith(" const"):
        name = name[:-6]
    if not name.endswith(")"):
        return name
    depth = 0
    for i in range(len(name) - 1, -1, -1):
        c = name[i]
        if c == ")":
            depth += 1
        elif c == "(":
            depth -= 1
            if depth == 0:
                head = name[:i]
                if head and not head.endswith("operator"):
                    return head
                return name
    return name


def symbol_name(sym):
    name = sym.GetName() or ""
    # Drop ELF symbol versions such as "@@GLIBC_2.34".
    if "@" in name[1:]:
        name = name[0] + name[1:].split("@", 1)[0]
    return strip_params(name)


def symbol_start(target, a):
    sym = resolve(target, a).GetSymbol()
    if not sym.IsValid():
        return None
    return load_addr(sym.GetStartAddress(), target)


def symbolize(target, a):
    sbaddr = resolve(target, a)
    if not sbaddr.IsValid():
        return None
    mod = sbaddr.GetModule()
    sym = sbaddr.GetSymbol()
    if sym.IsValid():
        start = load_addr(sym.GetStartAddress(), target)
        name = symbol_name(sym)
        s = "%s!%s" % (module_name(mod), name) if mod.IsValid() else name
        off = a - start
        return s + ("+0x%x" % off if off > 0 else "")
    if mod.IsValid():
        base = module_range(target, mod)[0]
        if base is not None and a >= base:
            return "%s+0x%x" % (module_name(mod), a - base)
        return module_name(mod)
    return None


def ascii_char(b):
    if b is None:
        return "?"
    return chr(b) if 0x20 <= b < 0x7F else "."


def hexdump_line(a, chunk, ptrsize):
    parts = []
    for i in range(16):
        if i < len(chunk):
            s = "??" if chunk[i] is None else "%02x" % chunk[i]
            sep = "-" if i == 8 else " "
        else:
            s = "  "
            sep = " "
        parts.append((sep if i else "") + s)
    return "%s  %s  %s" % (addr(a, ptrsize), "".join(parts), "".join(ascii_char(b) for b in chunk))
