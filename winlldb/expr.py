"""WinDbg MASM-style expression evaluator.

The resolver passed to evaluate() must provide: ptrsize, register_value(name, quiet=False),
pseudo_value(name), symbol_address(name) and read_uint(addr, size).
"""
import re

from .registry import WinDbgError

MASK = (1 << 64) - 1

_TOKEN = re.compile(r"""\s*(?:
    (?P<num>(?:0[xX][0-9a-fA-F`]+|0[nN][0-9]+|0[yY][01]+|[0-9][0-9a-fA-F`]*[hH]?)(?![\w$!@.:]))
  | (?P<ident>[A-Za-z_][\w.\-]*![\w$@.:~]+|[@$A-Za-z_][\w$@!.:]*)
  | (?P<op><<|>>|[-+*/%&|^~(),])
)""", re.X)

_HEX_ONLY = re.compile(r"[0-9a-fA-F`]+")

BINARY = {"|": 1, "^": 2, "&": 3, "<<": 4, ">>": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}
FUNCS = {"poi": None, "by": 1, "wo": 2, "dwo": 4, "qwo": 8}


def parse_number(s):
    t = s.replace("`", "").lower()
    try:
        if t.startswith("0x"):
            return int(t[2:], 16)
        if t.startswith("0n"):
            return int(t[2:], 10)
        if t.startswith("0y"):
            return int(t[2:], 2)
        if t.endswith("h"):
            return int(t[:-1], 16)
        return int(t, 16)
    except ValueError:
        raise WinDbgError("Syntax error in number '%s'" % s)


def tokenize(text):
    text = text.strip()
    toks = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.lastgroup is None:
            raise WinDbgError("Syntax error at '%s'" % text[pos:].strip())
        toks.append((m.lastgroup, m.group(m.lastgroup)))
        pos = m.end()
    return toks


def is_symbol_name(text):
    """True if text is a single plain symbol like `foo` or `mod!ns::foo` (no operators/registers/numbers)."""
    toks = tokenize(text)
    if len(toks) != 1 or toks[0][0] != "ident":
        return False
    name = toks[0][1]
    return not name.startswith(("@", "$")) and not _HEX_ONLY.fullmatch(name)


def resolve_ident(name, res):
    if name.startswith("@"):
        n = name[1:]
        if n.startswith("$"):
            return res.pseudo_value(n[1:])
        v = res.register_value(n)
        if v is None:
            raise WinDbgError("Bad register error at '%s'" % name)
        return v
    if name.startswith("$"):
        return res.pseudo_value(name[1:])
    if _HEX_ONLY.fullmatch(name):
        return int(name.replace("`", ""), 16)
    v = res.symbol_address(name)
    if v is not None:
        return v
    if "!" not in name:
        v = res.register_value(name, quiet=True)
        if v is not None:
            return v
    raise WinDbgError("Couldn't resolve error at '%s'" % name)


class _Parser:
    def __init__(self, toks, res):
        self.toks = toks
        self.i = 0
        self.res = res

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, val):
        kind, v = self.next()
        if v != val:
            raise WinDbgError("Syntax error: expected '%s'" % val)

    def expr(self, minp=1):
        left = self.unary()
        while True:
            kind, val = self.peek()
            if kind != "op" or val not in BINARY or BINARY[val] < minp:
                return left
            self.next()
            right = self.expr(BINARY[val] + 1)
            left = _apply(val, left, right)

    def unary(self):
        kind, val = self.next()
        if kind is None:
            raise WinDbgError("Syntax error: missing operand")
        if kind == "op":
            if val == "-":
                return -self.unary()
            if val == "+":
                return self.unary()
            if val == "~":
                return ~self.unary() & MASK
            if val == "(":
                v = self.expr()
                self.expect(")")
                return v
            raise WinDbgError("Syntax error at '%s'" % val)
        if kind == "num":
            return parse_number(val)
        low = val.lower()
        if low in FUNCS and self.peek() == ("op", "("):
            self.next()
            a = self.expr()
            self.expect(")")
            return self.res.read_uint(a & MASK, FUNCS[low] or self.res.ptrsize)
        return resolve_ident(val, self.res)


def _apply(op, l, r):
    if op == "+":
        return l + r
    if op == "-":
        return l - r
    if op == "*":
        return l * r
    if op in ("/", "%"):
        r &= MASK
        if r == 0:
            raise WinDbgError("Divide by zero")
        return (l & MASK) // r if op == "/" else (l & MASK) % r
    if op == "&":
        return l & r
    if op == "|":
        return l | r
    if op == "^":
        return l ^ r
    if op == "<<":
        return l << (r & 63)
    if op == ">>":
        return (l & MASK) >> (r & 63)
    raise WinDbgError("Unknown operator '%s'" % op)


def evaluate(text, res):
    toks = tokenize(text)
    if not toks:
        raise WinDbgError("Missing expression")
    p = _Parser(toks, res)
    v = p.expr()
    if p.i != len(toks):
        raise WinDbgError("Syntax error at '%s'" % p.peek()[1])
    return v & MASK
