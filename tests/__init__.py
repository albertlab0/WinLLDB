import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lldb_python_path():
    try:
        return subprocess.check_output(["lldb", "-P"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _setup_lldb():
    pypath = _lldb_python_path()
    # Outside the lldb binary (e.g. Debian/Ubuntu packages) liblldb may not find lldb-server on its own.
    if "LLDB_DEBUGSERVER_PATH" not in os.environ:
        candidates = []
        if pypath:
            candidates.append(os.path.join(pypath, "..", "..", "..", "bin", "lldb-server"))
        candidates.append(shutil.which("lldb-server") or "")
        for c in candidates:
            if c and os.path.exists(c):
                os.environ["LLDB_DEBUGSERVER_PATH"] = os.path.realpath(c)
                break
    try:
        import lldb  # noqa: F401
    except ImportError:
        if pypath:
            sys.path.insert(0, pypath)


_setup_lldb()
if REPO not in sys.path:
    sys.path.insert(0, REPO)
