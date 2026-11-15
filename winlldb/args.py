import re

from .registry import WinDbgError

_COUNT = re.compile(r"^[lL](\?)?(.*)$")
MAX_RANGE = 0x10000000


def split(text):
    """Whitespace split that keeps (...) groups and "..." strings together."""
    toks, cur = [], []
    depth = 0
    quote = False
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == '"':
                quote = False
            continue
        if ch == '"':
            quote = True
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch.isspace() and depth == 0:
            if cur:
                toks.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if quote:
        raise WinDbgError("Unterminated string")
    if cur:
        toks.append("".join(cur))
    return toks


def unquote(tok):
    if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
        return tok[1:-1]
    return tok


class Range:
    def __init__(self):
        self.start = None
        self.count = None
        self.end = None
        self.explicit = False
        self.rest = []


def parse_range(ctx, toks, default_count=None, elem_size=1, allow_end=True):
    """Parse `addr [L[?]count | endaddr] rest...`. Counts are in elements of elem_size."""
    r = Range()
    toks = list(toks)
    r.count = default_count
    if not toks:
        return r
    if not _COUNT.match(toks[0]) or _evaluates(ctx, toks[0]):
        r.start = ctx.eval(toks.pop(0))
    if toks:
        m = _COUNT.match(toks[0])
        if m and _is_count(ctx, m.group(2), toks):
            toks.pop(0)
            big, text = m.group(1), m.group(2)
            if not text:
                if not toks:
                    raise WinDbgError("Missing count after 'L'")
                text = toks.pop(0)
            r.count = ctx.eval(text)
            r.explicit = True
            if not big and elem_size and r.count * elem_size > MAX_RANGE:
                raise WinDbgError("Range error: size too large (use L? to override)")
        elif allow_end and r.start is not None:
            r.end = ctx.eval(toks.pop(0))
            if r.end < r.start:
                raise WinDbgError("Range error: end address is before start address")
            r.explicit = True
            if elem_size:
                r.count = (r.end - r.start) // elem_size + 1
    r.rest = toks
    return r


def _evaluates(ctx, text):
    try:
        ctx.eval(text)
        return True
    except WinDbgError:
        return False


def _is_count(ctx, text, toks):
    if not text:
        return len(toks) > 1
    return _evaluates(ctx, text)
