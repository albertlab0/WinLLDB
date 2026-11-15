import os
import re
import shutil
import subprocess
import unittest

from tests import REPO

try:
    import lldb
except ImportError:
    lldb = None

SRC = os.path.join(REPO, "tests", "fixtures", "sample.c")
BUILD = os.path.join(REPO, "build")
SAMPLE = os.path.join(BUILD, "sample")
ADDR = re.compile(r"^([0-9a-f]{8}`[0-9a-f]{8})")


def build_sample():
    if os.path.exists(SAMPLE) and os.path.getmtime(SAMPLE) >= os.path.getmtime(SRC):
        return
    cc = shutil.which("clang") or shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        raise unittest.SkipTest("no C compiler found")
    os.makedirs(BUILD, exist_ok=True)
    subprocess.check_call([cc, "-g", "-O0", "-fno-omit-frame-pointer", SRC, "-o", SAMPLE])


def parse_addr(line):
    m = ADDR.match(line)
    return int(m.group(1).replace("`", ""), 16) if m else None


class Session:
    def __init__(self, stop_at="leaf"):
        if lldb is None:
            raise unittest.SkipTest("lldb Python module not available")
        build_sample()
        self.dbg = lldb.SBDebugger.Create(False)
        self.dbg.SetAsync(False)
        self.ok("command script import " + os.path.join(REPO, "winlldb"))
        self.ok('target create "%s"' % SAMPLE)
        if stop_at:
            self.ok("bp " + stop_at)
            self.ok("process launch -o /dev/null")
            if self.dbg.GetSelectedTarget().GetProcess().GetState() != lldb.eStateStopped:
                raise unittest.SkipTest("could not launch the sample under lldb (ptrace restricted?)")

    def run(self, cmd):
        res = lldb.SBCommandReturnObject()
        self.dbg.GetCommandInterpreter().HandleCommand(cmd, res)
        return res.Succeeded(), res.GetOutput() or "", res.GetError() or ""

    def ok(self, cmd):
        ok, out, err = self.run(cmd)
        if not ok:
            raise AssertionError("%r failed: %s" % (cmd, err))
        return out

    def fail(self, cmd):
        ok, out, err = self.run(cmd)
        if ok:
            raise AssertionError("%r unexpectedly succeeded: %s" % (cmd, out))
        return err

    def lines(self, cmd):
        return [l for l in self.ok(cmd).splitlines() if l.strip()]

    def close(self):
        p = self.dbg.GetSelectedTarget().GetProcess()
        if p.IsValid():
            p.Kill()
        lldb.SBDebugger.Destroy(self.dbg)


class SessionTest(unittest.TestCase):
    stop_at = "leaf"

    @classmethod
    def setUpClass(cls):
        cls.s = Session(cls.stop_at)

    @classmethod
    def tearDownClass(cls):
        cls.s.close()
