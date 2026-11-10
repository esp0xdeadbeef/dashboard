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
# Prompts that do not run the commands you would type at a shell.
_UNSAFE_KINDS = ("password", "menu")

# Prompts that DO run commands, but under a different grammar: a QEMU monitor
# answers `info status`, not `ip a`, and silently rejects the rest with
# "unknown command". They are safe for a caller that means to drive them, and
# dangerous for one that thinks it is at a shell -- so they are opt-in rather
# than unconditionally unsafe.
NESTED_KINDS = ("repl",)


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

    def is_nested_shell(self) -> bool:
        """True when this is a sub-prompt (a REPL/monitor), not the shell.

        A caller that expects a shell must not type shell commands into one of
        these: the command is accepted and then rejected by the inner
        interpreter, which looks like a silent failure.
        """
        return self.kind in NESTED_KINDS

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
    """Match one already-captured line against learned prompts, then the table.

    Learned prompts come first because they were observed on this target: if a
    pane has already been seen at this exact prompt while its process state
    said "ready", that is stronger evidence than a regex written in advance.
    """
    line = line.rstrip()
    if not line.strip():
        return None
    learned_match = match_learned(line, depth, pid)
    if learned_match is not None:
        return learned_match
    for spec in load():
        if spec.matches(line):
            return PromptMatch(spec.tool, spec.kind, line, depth, pid)
    return None


def last_line(screen: str) -> str:
    for line in reversed(screen.splitlines()):
        if line.strip():
            return line.rstrip()
    return ""


# Text that asynchronous writers (the kernel, a supervisor, a journal
# forwarder) append to a console at any moment, including *onto a prompt line*.
# A prompt followed by such text is still a prompt: the console wrote the noise
# over the line rather than after it, and naive "match the last line" detection
# misses it.
# The rule is structural, not a list of programs: asynchronous writers label
# their lines with a timestamp. Three shapes cover effectively everything that
# lands on a console:
#
#   [   12.345678]          kernel printk, seconds since boot
#   [  OK  ] / [FAILED]     boot status
#   Nov 10 17:07:23 host    syslog/journal forwarding
#
# Anything else is treated as meaningful text. Naming particular daemons here
# would encode one machine's chatter into a general library.
CONSOLE_NOISE = re.compile(
    r"(?:\[\s*\d+\.\d+\]"                          # kernel printk stamp
    r"|^\s*\[\s*(?:OK|FAILED|\*|INFO|WARN)\]"        # boot status
    r"|^\s*\d{4}-\d\d-\d\d[T ]\d\d:"             # ISO/RFC3339 stamp
    r"|^\s*[A-Z][a-z]{2} +\d+ \d\d:\d\d:\d\d "    # syslog stamp
    r")"
)


def strip_console_noise(screen: str) -> str:
    """Return `screen` with asynchronous console noise removed.

    Two shapes are handled, and the second is why this cannot simply drop
    matching lines:

      * a line that is *only* noise is dropped;
      * a line that starts with a real prompt and then has noise written over
        it ("[root@host ~]# [ 33.5] something ...") is truncated at the noise,
        so the prompt survives.

    Truncating rather than dropping is essential: dropping would delete the
    prompt and make a ready pane look busy.
    """
    out = []
    for line in screen.splitlines():
        m = CONSOLE_NOISE.search(line)
        if m is None:
            out.append(line)
            continue
        head = line[: m.start()].rstrip()
        if head and match_line(head) is not None:
            out.append(head)
        # else: the line carries no prompt, only noise - drop it.
    return "\n".join(out)


def match_screen(screen: str, depth: int = 0, pid: int | None = None,
                 noise: bool = True, after: str | None = None
                 ) -> PromptMatch | None:
    """Match the prompt the screen is currently showing.

    `noise` strips asynchronous console noise first (kernel printk, journal
    forwarding, supervisor messages). Without it, a prompt that has had a log
    line written over it is invisible.

    `after`, when given, restricts matching to the text following the *last*
    occurrence of that marker. This is what distinguishes "the prompt from
    before my command" from "the prompt my command returned to" -- the marker
    is echoed by the terminal as well, so the last occurrence is the real one.
    """
    if after is not None:
        idx = screen.rfind(after)
        if idx >= 0:
            screen = screen[idx + len(after):]
    if noise:
        screen = strip_console_noise(screen)
    return match_line(last_line(screen), depth, pid)


def is_password_prompt(screen: str) -> bool:
    m = match_screen(screen)
    return m is not None and m.kind == "password"


# ------------------------------------------------------- learned prompts ---
#
# The table above is a *guess* about what prompts look like, and it will always
# be missing the next one: a themed shell's "└─[#]", a host-specific PS1, a
# vendor CLI. For a pane running an ordinary program that does not matter --
# termstate's process-state check answers "is it waiting?" without looking at
# the screen. But a pane that *hosts* another terminal (a QEMU serial console,
# screen, a nested tmux) has no useful process state, so the screen is the only
# signal, and a missing regex means "never ready".
#
# So prompts are also learned, empirically, from panes where the answer is
# already known:
#
#   * process state says the tty owner is blocked reading  -> it is at a prompt
#   * the last non-blank line of the screen                -> that prompt's text
#
# Recorded prompts are generalised to a pattern (digits, host names, paths,
# usernames and timestamps vary between redraws) and matched *before* the
# table, since they were observed on this very target. Nothing is guessed and
# nothing is written to disk: a learned prompt is a fact about a pane that was
# observed, and it disappears with the run.
#
# This is why a new shell prompt needs no code change: the first pane that
# shows it at a known-ready moment teaches it.

_learned: list[PromptSpec] = []
_LEARNED_LIMIT = 200

# Candidates, not yet promoted to `_learned`: (pattern, tool, kind, count).
# A line becomes a prompt only after it has been observed at a known-ready
# moment *repeatedly*. One sighting is not evidence -- a command's output line
# is also the last line of a READY pane for as long as you look at it, and
# learning that would mean the dashboard remembers an error message as a
# prompt forever. A prompt reappears; output does not.
_candidates: dict[str, list] = {}
LEARN_AFTER = 2

# Things that change between two redraws of the same prompt, and must not be
# part of the recorded pattern. Order matters: longer shapes first.
_VOLATILE = (
    (re.compile(r"\b\d{1,2}:\d\d(:\d\d)?\b"), r"\d{1,2}:\d\d(:\d\d)?"),
    (re.compile(r"\b\d{4}-\d\d-\d\d\b"), r"\d{4}-\d\d-\d\d"),
    (re.compile(r"\b\d+\b"), r"\d+"),
)


def generalise(line: str) -> str:
    """Turn one observed prompt line into a regex that matches its redraws.

    The prompt is captured at one instant, but the same prompt redraws with a
    different time, a different index, sometimes a different directory. Those
    parts must become wildcards, or the pattern would match exactly once.

    Escaping and substitution cannot be done in one pass: inserting "<time>"
    into already-escaped text would make the placeholder literal. So the line
    is cut at each volatile span, the literal parts are escaped, and the spans
    become their own regex alternatives.
    """
    spans = []          # (start, end, regex) for each volatile piece
    for volatile, replacement in _VOLATILE:
        for m in volatile.finditer(line):
            # Skip overlaps; the first (longest-shape-first) rule wins.
            if any(not (m.end() <= s or m.start() >= e) for s, e, _ in spans):
                continue
            spans.append((m.start(), m.end(), replacement))
    spans.sort()

    pattern = []
    cursor = 0
    for start, end, regex in spans:
        pattern.append(re.escape(line[cursor:start]))
        pattern.append(regex)
        cursor = end
    pattern.append(re.escape(line[cursor:]))
    return "^" + "".join(pattern).strip() + r"\s*$"


def learn(line: str, tool: str = "learned", kind: str = "shell",
          threshold: int | None = None) -> None:
    """Offer `line` as a prompt, observed at a moment the pane was ready.

    Promotion is not immediate: the line has to be offered `LEARN_AFTER` times
    (see `_candidates`) before it is trusted. A real prompt is re-offered on
    every look; a stray output line usually is not, and if it is, the pane
    really is sitting at the prompt with that line as its tail -- in which case
    matching it is also correct.
    """
    text = line.strip()
    if not text:
        return
    pattern = generalise(text)
    for spec in _learned:
        if spec.pattern == pattern:
            return
    try:
        re.compile(pattern)
    except re.error:
        return

    need = LEARN_AFTER if threshold is None else threshold
    entry = _candidates.setdefault(pattern, [tool, kind, 0])
    entry[2] += 1
    if entry[2] < need:
        return

    _candidates.pop(pattern, None)
    _learned.append(PromptSpec(tool, kind, pattern))
    # Oldest out first: a run that walks through many prompts should not grow
    # without bound.
    if len(_learned) > _LEARNED_LIMIT:
        del _learned[: len(_learned) - _LEARNED_LIMIT]


def forget_learned() -> None:
    """Drop everything learned (tests, and switching target mid-run)."""
    _learned.clear()
    _candidates.clear()


def learned() -> tuple[PromptSpec, ...]:
    return tuple(_learned)


def match_learned(line: str, depth: int = 0, pid: int | None = None
                  ) -> PromptMatch | None:
    """Match a previously learned prompt."""
    line = line.rstrip()
    if not line.strip():
        return None
    for spec in reversed(_learned):  # newest first: most likely to fit
        if spec.matches(line):
            return PromptMatch(spec.tool, spec.kind, line, depth, pid)
    return None


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
