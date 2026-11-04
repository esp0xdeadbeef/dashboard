"""prompts.py - known interactive prompts, loaded from prompts.txt.

Why a data file
---------------
Prompts nest, and the nesting is what breaks naive detection:

    msf6 >                                  framework
    msf6 exploit(windows/smb/...) >         module selected
    meterpreter >                           session opened
    meterpreter > shell                     shell on the target
    C:\\Windows\\system32>                   the target's shell

Each step is a *different prompt in the same pane*. So "what is this pane
asking" is a property of the deepest process in the pane, and it must be
re-evaluated whenever the process chain changes.

prompts.txt holds the table (tool, kind, regex) so adding a prompt needs no
code change. This module only knows how to load it and how to match.

There is no library to import for this. Verified against the real tools:

  * pexpect injects its own marker ([PEXPECT_PROMPT>) instead of guessing
  * pxssh forces the remote PS1 to a fixed marker
  * shutit uses one regex, '\\n.*[@#$] ', then makes the prompt predictable
  * autopexpect just sleeps 2s and records keystrokes
  * ansible takes a user-supplied prompt_regex per task

So the consensus is: make the prompt predictable, or accept a small curated
table. This is that table, and it is a *secondary* signal - termstate.py's
process-state check is primary because it works for prompts nobody has
written a regex for (and for readers that print nothing at all).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "prompts.txt")

KINDS = ("shell", "repl", "menu", "password", "fullscreen")

# Prompts where sending a command line would be harmful or meaningless.
_UNSAFE_KINDS = ("password", "menu")


@dataclass(frozen=True)
class PromptSpec:
    tool: str
    kind: str
    pattern: str

    def matches(self, line: str) -> bool:
        return re.search(self.pattern, line) is not None


@dataclass(frozen=True)
class PromptMatch:
    tool: str
    kind: str
    line: str
    depth: int = 0          # how deep in the process chain this was matched
    pid: int | None = None

    @property
    def safe_to_send(self) -> bool:
        """False for prompts that would consume or misuse a command line."""
        return self.kind not in _UNSAFE_KINDS

    def __str__(self) -> str:
        where = f"{self.tool} ({self.kind})"
        if self.pid is not None:
            where += f" pid={self.pid} depth={self.depth}"
        return f"{where}: {self.line!r}"


_cache: tuple[PromptSpec, ...] | None = None
_cache_mtime: float | None = None


def load(path: str | None = None) -> tuple[PromptSpec, ...]:
    """Load the spec table, re-reading prompts.txt if it changed on disk."""
    global _cache, _cache_mtime
    path = path or DEFAULT_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        if _cache is None:
            _cache = ()
        return _cache
    if _cache is not None and _cache_mtime == mtime:
        return _cache

    specs: list[PromptSpec] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                raise ValueError(
                    f"{path}:{lineno}: expected tool<TAB>kind<TAB>regex, "
                    f"got {line!r}"
                )
            tool, kind, pattern = (p.strip() for p in parts)
            if kind not in KINDS:
                raise ValueError(
                    f"{path}:{lineno}: unknown kind {kind!r} "
                    f"(expected one of {', '.join(KINDS)})"
                )
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"{path}:{lineno}: bad regex {pattern!r}: {exc}"
                ) from exc
            specs.append(PromptSpec(tool, kind, pattern))

    if not specs:
        raise ValueError(f"{path}: no prompt specs found")
    _cache = tuple(specs)
    _cache_mtime = mtime
    return _cache


def specs() -> tuple[PromptSpec, ...]:
    return load()


def match_line(line: str, depth: int = 0, pid: int | None = None
               ) -> PromptMatch | None:
    """Match one already-captured line against the table."""
    line = line.rstrip()
    if not line.strip():
        return None
    for spec in load():
        if spec.matches(line):
            return PromptMatch(spec.tool, spec.kind, line, depth, pid)
    return None


def last_line(screen: str) -> str:
    for line in reversed(screen.splitlines()):
        if line.strip():
            return line.rstrip()
    return ""


def match_screen(screen: str, depth: int = 0, pid: int | None = None
                 ) -> PromptMatch | None:
    return match_line(last_line(screen), depth, pid)


def is_password_prompt(screen: str) -> bool:
    m = match_screen(screen)
    return m is not None and m.kind == "password"


# ----------------------------------------------------------- chain scanning ---

def chain_prompts(lines_by_depth: dict[int, str]) -> list[PromptMatch]:
    """Match each level of a nested process chain.

    `lines_by_depth` maps depth -> the last line of the pane as observed for
    that level. In practice callers pass the same screen repeated, because a
    pane shows one screen; the value of this function is that it returns the
    *deepest* recognised prompt, which is the one actually waiting for input.

    Returns matches ordered shallow -> deep, so the last element is the
    innermost prompt.
    """
    out: list[PromptMatch] = []
    for depth in sorted(lines_by_depth):
        m = match_line(lines_by_depth[depth], depth=depth)
        if m is not None:
            out.append(m)
    return out


def deepest(matches: list[PromptMatch]) -> PromptMatch | None:
    return matches[-1] if matches else None
