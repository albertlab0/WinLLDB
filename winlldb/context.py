import lldb

from . import expr, fmt
from .registry import WinDbgError

PAGE = 0x1000
_LIVE = (lldb.eStateStopped, lldb.eStateCrashed, lldb.eStateSuspended)
_X86 = ("x86_64", "x86_64h", "i386", "i486", "i586", "i686")


class Ctx:
    def __init__(self, debugger, exe_ctx, result):
        self.debugger = debugger
        self.exe_ctx = exe_ctx
        self.result = result
        self._out = []

    # ---- output ----
    def write(self, text=""):
        self._out.append(text if text.endswith("\n") else text + "\n")

    def flush(self):
        if self._out:
            self.result.PutCString("".join(self._out))
            self._out = []

    def run(self, cmd):
        """Run an LLDB command synchronously, appending its output."""
        res = lldb.SBCommandReturnObject()
        was_async = self.debugger.GetAsync()
        self.debugger.SetAsync(False)
        try:
            self.debugger.GetCommandInterpreter().HandleCommand(cmd, res)
        finally:
            self.debugger.SetAsync(was_async)
        out, err = res.GetOutput() or "", res.GetError() or ""
        if out:
            self.write(out)
        if not res.Succeeded():
            raise WinDbgError(err.strip() or "'%s' failed" % cmd)
        if err:
            self.write(err)

    # ---- execution context ----
    @property
    def target(self):
        t = self.exe_ctx.GetTarget() if self.exe_ctx is not None else None
        if t is None or not t.IsValid():
            t = self.debugger.GetSelectedTarget()
        if not t.IsValid():
            raise WinDbgError("No target. Use 'target create <file>' first.")
        return t

    def live_process(self):
        p = self.target.GetProcess()
        if p.IsValid() and p.GetState() in _LIVE:
            return p
        return None

    @property
    def process(self):
        p = self.live_process()
        if p is None:
            raise WinDbgError("No stopped process (use 'g' to start the target)")
        return p

    @property
    def thread(self):
        t = self.process.GetSelectedThread()
        if not t.IsValid():
            raise WinDbgError("No thread selected")
        return t

    @property
    def frame(self):
        f = self.thread.GetSelectedFrame()
        if not f.IsValid():
            raise WinDbgError("No frame selected")
        return f

    @property
    def ptrsize(self):
        return self.target.GetAddressByteSize() or 8

    @property
    def byteorder(self):
        return "big" if self.target.GetByteOrder() == lldb.eByteOrderBig else "little"

    @property
    def arch(self):
        return (self.target.GetTriple() or "").split("-")[0]

    def is_x86(self):
        return self.arch in _X86

    def eval(self, text):
        return expr.evaluate(text, self)

    # ---- memory ----
    def _read_raw(self, a, size):
        err = lldb.SBError()
        p = self.live_process()
        if p is not None:
            data = p.ReadMemory(a, size, err)
        else:
            data = self.target.ReadMemory(fmt.resolve(self.target, a), size, err)
        if err.Fail() or data is None:
            return None
        return bytes(data)

    def read(self, a, size):
        data = self._read_raw(a, size)
        if data is None or len(data) < size:
            raise WinDbgError("Memory access error at %s" % fmt.addr(a, self.ptrsize))
        return data

    def read_partial(self, a, size):
        """Read size bytes as a list of ints, with None for unreadable bytes."""
        if size <= 0:
            return []
        data = self._read_raw(a, size)
        if data is not None and len(data) == size:
            return list(data)
        out = []
        cur, end = a, a + size
        while cur < end:
            nxt = min(end, (cur // PAGE + 1) * PAGE)
            d = self._read_raw(cur, nxt - cur) or b""
            out.extend(d[: nxt - cur])
            out.extend([None] * (nxt - cur - len(d)))
            cur = nxt
        return out

    def read_uint(self, a, size):
        return int.from_bytes(self.read(a, size), self.byteorder)

    # ---- expression resolver ----
    def register_value(self, name, quiet=False):
        if self.live_process() is None:
            if quiet:
                return None
            raise WinDbgError("No process; cannot read register '%s'" % name)
        reg = self.frame.FindRegister(name)
        if not reg.IsValid() or reg.GetValue() is None:
            return None
        return reg.GetValueAsUnsigned()

    def pseudo_value(self, name):
        n = name.lower()
        if n == "ip":
            return self.frame.GetPC()
        if n in ("sp", "csp"):
            return self.frame.GetSP()
        if n == "ra":
            f = self.thread.GetFrameAtIndex(self.frame.GetFrameID() + 1)
            if not f.IsValid():
                raise WinDbgError("No return address")
            return f.GetPC()
        if n == "retreg":
            for r in ("rax", "eax", "x0", "r0"):
                v = self.register_value(r)
                if v is not None:
                    return v
        if n == "exentry":
            m = self.target.GetModuleAtIndex(0)
            return fmt.load_addr(m.GetObjectFileEntryPointAddress(), self.target)
        if n == "ptrsize":
            return self.ptrsize
        if n == "tpid":
            return self.process.GetProcessID()
        if n == "tid":
            return self.thread.GetThreadID()
        raise WinDbgError("Bad pseudo-register error at '$%s'" % name)

    def find_modules(self, name):
        name = name.lower()
        out = []
        for m in self.target.module_iter():
            fn = (m.GetFileSpec().GetFilename() or "").lower()
            if fn == name or fmt.module_name(m).lower() == name:
                out.append(m)
        return out

    def _first_symbol_addr(self, scl):
        for i in range(scl.GetSize()):
            sc = scl.GetContextAtIndex(i)
            for obj in (sc.GetSymbol(), sc.GetFunction()):
                if obj.IsValid():
                    a = fmt.load_addr(obj.GetStartAddress(), self.target)
                    if a != fmt.INVALID:
                        return a
        return None

    def symbol_address(self, name):
        target = self.target
        if "!" in name:
            modname, sym = name.split("!", 1)
            for m in self.find_modules(modname):
                a = self._first_symbol_addr(m.FindSymbols(sym))
                if a is None:
                    a = self._first_symbol_addr(m.FindFunctions(sym, lldb.eFunctionNameTypeAuto))
                if a is not None:
                    return a
            return None
        if self.live_process() is not None:
            v = self.frame.FindVariable(name)
            if v.IsValid() and v.GetLoadAddress() != fmt.INVALID:
                return v.GetLoadAddress()
        a = self._first_symbol_addr(target.FindSymbols(name))
        if a is None:
            a = self._first_symbol_addr(target.FindFunctions(name, lldb.eFunctionNameTypeAuto))
        if a is None:
            g = target.FindFirstGlobalVariable(name)
            if g.IsValid() and g.GetLoadAddress() != fmt.INVALID:
                a = g.GetLoadAddress()
        return a
