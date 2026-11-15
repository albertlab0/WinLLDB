"""WinLLDB: WinDbg-style commands for LLDB.

Load with:  command script import /path/to/WinLLDB/winlldb
"""
from . import cmds  # noqa: F401  (registers commands)
from . import registry


def __lldb_init_module(debugger, internal_dict):
    registry.register_all(debugger)
    print("WinLLDB loaded: %d WinDbg commands. Type 'winhelp' for a list." % len(registry.COMMANDS))
