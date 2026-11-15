from .. import args, fmt, state
from ..registry import WinDbgError, command

G = "Memory"
_UNITS = {"b": 1, "w": 2, "d": 4, "q": 8, "c": 4}
_DEFAULT_BYTES = 0x80
_MAX_STRING = 0x400
_STRING_LINE = 48


def _unit(ctx, kind):
    return ctx.ptrsize if kind == "p" else _UNITS[kind]


def _start(ctx, rng):
    if rng.rest:
        raise WinDbgError("Extra argument '%s'" % rng.rest[0])
    if rng.start is not None:
        return rng.start
    st = state.get(ctx)
    if st.next_d is None:
        raise WinDbgError("No address given and no previous display address")
    return st.next_d


def _values(chunk, size, order):
    out = []
    for i in range(0, len(chunk), size):
        part = chunk[i:i + size]
        out.append(None if len(part) < size or None in part else int.from_bytes(bytes(part), order))
    return out


def _fmt_val(v, size):
    if size == 8:
        return "????????`????????" if v is None else fmt.addr(v, 8)
    return "?" * (2 * size) if v is None else "%0*x" % (2 * size, v)


@command("db", "db [addr] [L count | end]", "Display bytes with ASCII", G)
@command("dw", "dw [addr] [L count | end]", "Display 16-bit words", G)
@command("dd", "dd [addr] [L count | end]", "Display 32-bit dwords", G)
@command("dq", "dq [addr] [L count | end]", "Display 64-bit qwords", G)
@command("dp", "dp [addr] [L count | end]", "Display pointer-sized values", G)
@command("dc", "dc [addr] [L count | end]", "Display dwords with ASCII", G)
@command("d", "d [addr] [L count]", "Repeat the last d* display format", G)
def cmd_display(ctx, name, text):
    st = state.get(ctx)
    kind = st.last_d if name == "d" else name[1]
    if kind in ("a", "u"):
        return cmd_string(ctx, "d" + kind, text)
    size = _unit(ctx, kind)
    rng = args.parse_range(ctx, args.split(text), _DEFAULT_BYTES // size, size)
    start = _start(ctx, rng)
    total = rng.count * size
    data = ctx.read_partial(start, total)
    ps = ctx.ptrsize
    for off in range(0, total, 16):
        chunk = data[off:off + 16]
        a = start + off
        if kind == "b":
            ctx.write(fmt.hexdump_line(a, chunk, ps))
            continue
        vals = " ".join(_fmt_val(v, size) for v in _values(chunk, size, ctx.byteorder))
        line = "%s  %s" % (fmt.addr(a, ps), vals)
        if kind == "c":
            line = "%-*s  %s" % (len(fmt.addr(0, ps)) + 2 + 35, line, "".join(fmt.ascii_char(b) for b in chunk))
        ctx.write(line)
    st.next_d = start + total
    st.last_d = kind


@command("dps", "dps [addr] [L count]", "Display pointers with symbols", G)
@command("dds", "dds [addr] [L count]", "Display dwords with symbols", G)
@command("dqs", "dqs [addr] [L count]", "Display qwords with symbols", G)
def cmd_display_symbols(ctx, name, text):
    size = {"p": ctx.ptrsize, "d": 4, "q": 8}[name[1]]
    rng = args.parse_range(ctx, args.split(text), _DEFAULT_BYTES // size, size)
    start = _start(ctx, rng)
    data = ctx.read_partial(start, rng.count * size)
    vals = _values(data, size, ctx.byteorder)
    target, ps = ctx.target, ctx.ptrsize
    for i, v in enumerate(vals):
        sym = fmt.symbolize(target, v) if v else None
        line = "%s  %s" % (fmt.addr(start + i * size, ps), _fmt_val(v, size))
        ctx.write(line + (" " + sym if sym else ""))
    st = state.get(ctx)
    st.next_d = start + rng.count * size


def _char(v, unit):
    if unit == 1:
        return fmt.ascii_char(v)
    c = chr(v)
    return c if v >= 0x20 and c.isprintable() else "."


@command("da", "da [addr] [L count]", "Display ASCII string", G)
@command("du", "du [addr] [L count]", "Display UTF-16 string", G)
def cmd_string(ctx, name, text):
    unit = 1 if name == "da" else 2
    rng = args.parse_range(ctx, args.split(text), None, unit)
    start = _start(ctx, rng)
    maxu = rng.count if rng.count is not None else _MAX_STRING
    data = ctx.read_partial(start, maxu * unit)
    chars = []
    unreadable = False
    for i in range(maxu):
        part = data[i * unit:(i + 1) * unit]
        if len(part) < unit or None in part:
            unreadable = True
            break
        v = int.from_bytes(bytes(part), ctx.byteorder)
        if v == 0:
            break
        chars.append(v)
    ps = ctx.ptrsize
    if not chars and unreadable:
        ctx.write("%s  ????" % fmt.addr(start, ps))
    else:
        for j in range(0, max(len(chars), 1), _STRING_LINE):
            seg = "".join(_char(c, unit) for c in chars[j:j + _STRING_LINE])
            ctx.write('%s  "%s"' % (fmt.addr(start + j * unit, ps), seg))
    st = state.get(ctx)
    st.next_d = start + (len(chars) + 1) * unit
    st.last_d = name[1]
