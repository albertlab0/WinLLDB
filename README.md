# WinLLDB
A WinDbg command compatibility layer for LLDB, bringing familiar debugging workflows to Linux and macOS.

WinLLDB is a pure-Python LLDB extension. It adds the WinDbg commands you use every day (`dt`, `u`, `ub`, `db`, `dd`, `bp`, `bl`, `k`, `r`, `lm`, `x`, ...), with WinDbg-style syntax and output: backtick-split 64-bit addresses, `module!symbol+0x1a` names, `L` counts, MASM expressions, and 0-based breakpoint IDs.

```
(lldb) dt sample_s g_sample
   +0x000 a                : 0n5
   +0x008 name             : 0x00005555`55556038  "sample"
   +0x010 in               : inner
   +0x018 arr              : [4] 0n10
   +0x028 flags            : 0y101
   +0x02c c                : 0n2 ( BLUE )
(lldb) k
Child-SP          RetAddr               Call Site
00007fff`ffffd4e0 00005555`55555197     sample!leaf+0xb [/src/sample.c @ 31]
00007fff`ffffd4f0 00005555`5555528a     sample!middle+0x2b [/src/sample.c @ 38]
```

## Install

Requires LLDB with Python support (tested with LLDB 21).

```sh
git clone https://github.com/albertlab0/WinLLDB
echo "command script import $PWD/WinLLDB/winlldb" >> ~/.lldbinit
```

Or load it into a running session with `command script import /path/to/WinLLDB/winlldb`, then type `winhelp`.

## Commands

| Group | Commands |
|---|---|
| Memory | `db dw dd dq dp dc` `d` (repeat) `da du` `dps dds dqs` |
| Disassembly | `u ub uf` (`uf /c` lists calls) |
| Types | `dt [-r[N]] [-a[N]] [mod!]Type [addr] [field.sub]`, `dt var`, `dt mod!Pat*` |
| Breakpoints | `bp bu bm bl bc bd be` (`/1`, `/w "cond"`, pass count, `"cmd;cmd"`, `` `file.c:12` ``) |
| Execution | `g [addr]` `gu` `p` `t` `pt` `pc` `tc` `l+t` / `l-t` |
| Stack & threads | `k kn kb kv kp kc` (and `kbn kpn kvn`), `.frame [/r] N`, `~`, `~ Ns`, `~ * cmd` |
| Registers | `r`, `r rax,rbx`, `r rax=expr`, `r zf` |
| Symbols & search | `lm [v] [f] [m pat]` (`lmvm`), `x [/f /d] mod!pat`, `ln`, `s -b/-w/-d/-q/-a/-u`, `?`, `??`, `dv [/t /V /i]`, `.reload`, `.sympath` |

`winhelp` lists everything with usage. `help <cmd>` works too.

### Expressions
Commands that take an address accept WinDbg MASM expressions:
- Numbers are **hex by default**. Use `0n` for decimal, `0y` for binary, and `0x`/`h` for hex. Backticks are ignored (`7ff7`1a3b1000`).
- Registers: `@rsp`, `@rip`, or bare `rax`. Pseudo-registers: `@$ip`, `@$sp`, `@$ra`, `@$retreg`, `@$exentry`, `@$tid`, `@$tpid`.
- Symbols: `main`, `sample!leaf`, `libc!malloc`, `sample!ns::Foo::bar`. A local variable name gives its address.
- `poi()`, `by()`, `wo()`, `dwo()`, `qwo()`, the operators `+ - * / % & | ^ << >> ~`, and parentheses.
- Ranges: `addr L<count>`, `addr L?<count>` (lifts the 256 MB safety limit), or `start end`.

## Differences from WinDbg
- **LLDB aliases with the same names are overridden** while WinLLDB is loaded, notably `r`, `x`, `s`, `p`, `t` and `g`. The LLDB commands themselves stay available by their full names (`register read`, `memory read`, `thread step-in`, `expression`, ...).
- **Breakpoint IDs** are shown and accepted 0-based, so WinDbg ID = LLDB ID − 1. `g <addr>` creates a temporary breakpoint, which uses up an ID.
- **Threads**: LLDB can't parse `~0s` or `~*k` as single words. Put a space after `~`: `~ 0s`, `~ * k`.
- A name made only of hex digits (`add`, `cafe`) is read as a number. Use `mod!add` to mean the symbol.
- Module names drop their extensions: `libc.so.6` becomes `libc`.
- `p`/`t` step a source line when line info exists and an instruction otherwise. `l-t` forces instruction stepping.
- Breakpoint command strings run as LLDB commands, where WinLLDB commands also work. `g`/`gc` inside them become `process continue`.
- Not supported: `kb` home-space semantics (it shows the first arguments instead), WinDbg conditional scripting (`.if`, `j`), and the DML links in `bl`/`lm`.

## Development

```sh
python3 -m unittest discover -s tests -t .
```

The integration tests build `tests/fixtures/sample.c` with `clang`/`gcc` and run every command group against it through LLDB's Python API. The test bootstrap finds the `lldb` module with `lldb -P` and sets `LLDB_DEBUGSERVER_PATH` when needed.
