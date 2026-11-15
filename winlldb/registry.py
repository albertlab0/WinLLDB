import sys
import traceback

import lldb


class WinDbgError(Exception):
    pass


class Command:
    def __init__(self, name, func, usage, summary, group):
        self.name = name
        self.func = func
        self.usage = usage or name
        self.summary = summary
        self.group = group


COMMANDS = []


def command(name, usage="", summary="", group="Misc"):
    def deco(fn):
        COMMANDS.append(Command(name, fn, usage, summary, group))
        return fn
    return deco


def _entry_name(name):
    return "cmd_" + name.encode().hex()


def _make_entry(cmd):
    def entry(debugger, command_text, exe_ctx, result, internal_dict):
        from .context import Ctx
        ctx = Ctx(debugger, exe_ctx, result)
        try:
            out = cmd.func(ctx, cmd.name, command_text.strip())
            if out:
                ctx.write(out)
            ctx.flush()
            result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        except WinDbgError as e:
            ctx.flush()
            result.SetError(str(e))
        except Exception:
            ctx.flush()
            result.SetError("winlldb: internal error in '%s'\n%s" % (cmd.name, traceback.format_exc()))
    entry.__doc__ = "%s\n\n%s" % (cmd.usage, cmd.summary)
    return entry


def register_all(debugger):
    mod = sys.modules[__name__]
    for cmd in COMMANDS:
        fname = _entry_name(cmd.name)
        setattr(mod, fname, _make_entry(cmd))
        help_text = ("%s -- %s" % (cmd.usage, cmd.summary)).replace("\\", "\\\\").replace('"', '\\"')
        debugger.HandleCommand('command script add -o -h "%s" -f %s.%s %s' % (help_text, __name__, fname, cmd.name))
