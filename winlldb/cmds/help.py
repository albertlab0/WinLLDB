from ..registry import COMMANDS, command

_ORDER = ["Memory", "Disassembly", "Types", "Breakpoints", "Execution", "Stack & threads", "Registers",
          "Symbols & search", "Misc"]


@command("winhelp", "winhelp [command]", "List WinLLDB commands", "Misc")
def cmd_winhelp(ctx, name, text):
    if text:
        hits = [c for c in COMMANDS if c.name == text.strip()]
        for c in hits:
            ctx.write("%s\n    %s" % (c.usage, c.summary))
        if not hits:
            ctx.write("No WinLLDB command '%s'" % text.strip())
        return
    groups = {g: [] for g in _ORDER}
    for c in COMMANDS:
        groups.setdefault(c.group, []).append(c)
    width = 32
    for group, cmds in groups.items():
        ctx.write("%s:" % group)
        for c in sorted(cmds, key=lambda c: c.name):
            if len(c.usage) > width:
                ctx.write("  %s\n  %-*s  %s" % (c.usage, width, "", c.summary))
            else:
                ctx.write("  %-*s  %s" % (width, c.usage, c.summary))
        ctx.write("")
