"""termstate.py - decide whether a tmux pane is waiting for input.

The original dashboard answered "is this program at a prompt?" by typing 52
characters of junk into the pane, erasing them, sending C-m, and then
comparing the screen against a global list of remembered "interpreter"
strings. That is wrong for the cases that actually matter:

  * ``smbclient``/``ftp``/``mysql`` may print nothing at all, so there is no
    screen text to match.
  * a remote shell (``ssh``) has an arbitrary prompt, which never matches a
    remembered one.
  * ``msfconsole`` reads its own line editor, so it is never "the shell".
  * typing into any of these mutates what you are measuring, and can consume
    a password prompt.

Instead, ask the operating system. A program waiting for terminal input is
blocked in a read on the tty, and the kernel records why each process is
asleep in ``/proc/<pid>/wchan``. Combined with ``tpgid`` (which process group
the tty currently belongs to) that is enough to classify a pane without
sending a single keystroke.

The states we produce:

  READY      the foreground program is blocked reading the terminal, i.e. it
             wants input now. Safe to send a command.
  BUSY       the foreground program is working (has children, or is not
             blocked on a read).
  UNKNOWN    could not tell - be conservative and treat as busy.

Nothing here screen-scrapes, and nothing here writes to the pane.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from enum import Enum

READY = "READY"
BUSY = "BUSY"
UNKNOWN = "UNKNOWN"


class State(str, Enum):
    READY = READY
    BUSY = BUSY
    UNKNOWN = UNKNOWN


@dataclass(frozen=True)
class PaneState:
    state: State
    reason: str
    pid: int | None = None
    comm: str | None = None
    # Prompt table match for the deepest process, if the table knew it.
    prompt: object | None = None
    # Full ancestry shell -> deepest, for logging and for rescan detection.
    chain: tuple[int, ...] = ()

    @property
    def ready(self) -> bool:
        return self.state is State.READY

    @property
    def tool(self) -> str | None:
        return getattr(self.prompt, "tool", None)

    @property
    def safe_to_send(self) -> bool:
        """READY and not a password/menu prompt."""
        if not self.ready:
            return False
        pm = self.prompt
        if pm is None:
            return True
        return getattr(pm, "safe_to_send", True)


# Wake channels that mean "blocked on a read from the terminal".
#
#  wait_woken            - plain blocking read() (cat, nc, sh -c 'read x')
#  n_tty_read            - the tty line discipline itself, i.e. canonical
#                          mode input (bash, sh, most REPLs)
#  poll_schedule_timeout - selinux/poll(2) based line editors; bash's readline
#                          and python's input() commonly end up here
#  do_select             - older kernels express the same poll as select(2)
#  anon_pipe_read        - stdin/stdout are pipes (common for wrappers and for
#                          some REPLs, e.g. ruby's readline in msfconsole)
READ_WCHANS = (
    "wait_woken",
    "n_tty_read",
    "poll_schedule_timeout",
    "do_select",
    "anon_pipe_read",
    # epoll-based event loops reading the terminal: ipython (prompt_toolkit),
    # and anything else using an async reader. Observed at IPython's
    # "In [N]:" prompt.
    "do_epoll_wait",
    "ep_poll",
    "epoll_wait",
)

# Wake channels that mean "waiting for a child process", which is work, not a
# prompt.
WAIT_WCHANS = ("do_wait", "wait_consider_task")

# Wake channels that mean "running, waiting on internal locking / timers".
# A multi-threaded runtime (ruby/msfconsole, python, node) doing work parks
# its threads here. Not a prompt either.
WORK_WCHANS = (
    "futex_do_wait",
    # zsh parks in sigsuspend while a foreground job runs.
    "sigsuspend",
    "do_sigsuspend",
    "futex_wait_queue",
    "schedule_timeout",
    "hrtimer_nanosleep",
    "do_nanosleep",
    "nanosleep",
)

# Any process in these states cannot be an interactive prompt.
DEAD_STATES = ("Z", "X", "x")


def _read(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _proc_stat(pid: int) -> dict | None:
    raw = _read(f"/proc/{pid}/stat")
    if not raw:
        return None
    # comm is parenthesised and may contain spaces/parens; split around it.
    lparen, rparen = raw.find("("), raw.rfind(")")
    if lparen < 0 or rparen < 0:
        return None
    comm = raw[lparen + 1:rparen]
    rest = raw[rparen + 2:].split()
    if len(rest) < 3:
        return None
    return {
        "pid": pid,
        "comm": comm,
        "state": rest[0],
        # utime, stime are rest[11], rest[12]; ppid is rest[1]; tpgid rest[5]
        "ppid": int(rest[1]),
        "tpgid": int(rest[5]),
        "utime": int(rest[11]),
        "stime": int(rest[12]),
    }


def _wchan(pid: int) -> str:
    # /proc/<pid>/wchan names the kernel function; strip the GCC suffix
    # (poll_schedule_timeout.constprop.0 -> poll_schedule_timeout).
    raw = _read(f"/proc/{pid}/wchan") or ""
    return raw.split(".", 1)[0]


def _children(pid: int) -> list[int]:
    kids: list[int] = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            st = _proc_stat(int(entry))
            if st and st["ppid"] == pid:
                kids.append(int(entry))
    except OSError:
        pass
    return kids


def _descendants(pid: int) -> list[int]:
    out: list[int] = []
    frontier = [pid]
    while frontier:
        nxt: list[int] = []
        for p in frontier:
            for c in _children(p):
                out.append(c)
                nxt.append(c)
        frontier = nxt
    return out


def _pane_tty_owner(shell_pid: int) -> int | None:
    """Return the pid of the process that currently owns the pane's tty.

    ``tpgid`` on the shell tells us which process *group* holds the terminal.
    If that is the shell's own group, the shell owns it. Otherwise something
    the shell spawned owns it, and we should look at that process instead -
    this is what makes nested shells and ssh hops work.
    """
    st = _proc_stat(shell_pid)
    if st is None:
        return None
    tpgid = st["tpgid"]
    if tpgid <= 0:
        # No controlling terminal (or already detached).
        return None
    if tpgid == shell_pid:
        return shell_pid
    # tpgid is a process group id; find a live member of it. Prefer a direct
    # descendant of the shell, since that is the program the user started.
    candidates = [p for p in _descendants(shell_pid) if _proc_stat(p)]
    for pid in candidates:
        pst = _proc_stat(pid)
        if pst and pst["tpgid"] == tpgid and pst["state"] not in DEAD_STATES:
            # Walk down to the deepest live process in the group so that
            # e.g. bash -> ssh -> remote shell resolves to the last one.
            while True:
                kids = [k for k in _children(pid) if _proc_stat(k)
                        and _proc_stat(k)["tpgid"] == tpgid]
                if not kids:
                    break
                pid = kids[0]
            return pid
    # Fall back to any live process in that group.
    for pid in candidates:
        pst = _proc_stat(pid)
        if pst and pst["tpgid"] == tpgid and pst["state"] not in DEAD_STATES:
            return pid
    return None


def process_chain(shell_pid: int) -> list[int]:
    """Ancestry from the pane's shell down to the deepest live foreground
    process, inclusive.

    This is what makes nested prompts work: `msf6 >` becomes
    `msf6 exploit(...) >` becomes `meterpreter >` becomes `C:\\>` as each
    program spawns the next. Each entry is one level whose prompt can differ.
    """
    chain = [shell_pid]
    st = _proc_stat(shell_pid)
    if st is None:
        return chain
    tpgid = st["tpgid"]
    seen = {shell_pid}
    while True:
        cur = chain[-1]
        kids = [k for k in _children(cur) if _proc_stat(k)]
        if not kids:
            break
        # Prefer a child in the foreground process group.
        fg = [k for k in kids if _proc_stat(k)["tpgid"] == tpgid]
        nxt = (fg or kids)[0]
        if nxt in seen:
            break
        seen.add(nxt)
        chain.append(nxt)
    return chain


def classify(pid: int) -> PaneState:
    """Classify a single process as waiting-for-input or working."""
    st = _proc_stat(pid)
    if st is None:
        return PaneState(State.UNKNOWN, f"no such process {pid}", pid)
    if st["state"] in DEAD_STATES:
        return PaneState(State.UNKNOWN, f"{st['comm']} is {st['state']}", pid,
                         st["comm"])

    wchan = _wchan(pid)

    # Waiting on a child = running a command, not sitting at a prompt.
    if wchan in WAIT_WCHANS:
        return PaneState(State.BUSY, f"{st['comm']} is waiting for a child "
                         f"({wchan})", pid, st["comm"])

    if wchan in WORK_WCHANS:
        return PaneState(State.BUSY, f"{st['comm']} is working ({wchan})", pid,
                         st["comm"])

    live_kids = [k for k in _children(pid) if _proc_stat(k)]
    if live_kids:
        return PaneState(State.BUSY, f"{st['comm']} has {len(live_kids)} "
                         f"child process(es)", pid, st["comm"])

    if wchan in READ_WCHANS:
        return PaneState(State.READY, f"{st['comm']} is blocked reading the "
                         f"terminal ({wchan})", pid, st["comm"])

    # Stopped processes are not prompts.
    if st["state"] == "T":
        return PaneState(State.BUSY, f"{st['comm']} is stopped", pid,
                         st["comm"])

    return PaneState(State.UNKNOWN, f"{st['comm']} in state {st['state']} "
                     f"wchan={wchan or '?'}", pid, st["comm"])


def capture(target: str, scroll: int = 0) -> str:
    """Capture a pane's visible text."""
    args = ["tmux", "capture-pane", "-p", "-t", target]
    if scroll:
        args += ["-S", f"-{scroll}"]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def pane_state(target: str, rescan: bool = True) -> PaneState:
    """Classify a tmux pane target (session:window.pane).

    Two independent signals are combined:

    1. Process state (`classify`) - is the tty owner blocked reading? This is
       prompt-agnostic and the primary signal.
    2. The prompt table (`prompts.py`) - if the screen's last line matches a
       known prompt, we learn *which* tool is asking, so a shell command can
       be kept out of a password prompt or a pager.

    `rescan` matters because prompts nest: `msf6 >` -> `meterpreter >` ->
    `C:\\>`. Each time the process chain grows or shrinks, the prompt that is
    actually waiting for input changes, so the match is redone from scratch
    rather than cached.
    """
    try:
        out = subprocess.run(
            ["tmux", "display", "-p", "-t", target, "#{pane_pid}"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return PaneState(State.UNKNOWN, f"tmux query failed: {exc}")
    if out.returncode != 0:
        return PaneState(State.UNKNOWN,
                         f"no such pane {target!r}: {out.stderr.strip()}")
    try:
        shell_pid = int(out.stdout.strip())
    except ValueError:
        return PaneState(State.UNKNOWN, "tmux returned no pane pid")

    chain = tuple(process_chain(shell_pid)) if rescan else (shell_pid,)
    owner = _pane_tty_owner(shell_pid) or chain[-1] if chain else shell_pid
    base = classify(owner)

    # Prompt match, tagged with the depth of the process that owns the tty so
    # a nested prompt is distinguishable from the outer one.
    prompt = None
    if rescan:
        try:
            import prompts as _prompts
            depth = chain.index(owner) if owner in chain else len(chain) - 1
            prompt = _prompts.match_screen(capture(target), depth=depth,
                                           pid=owner)
        except Exception:  # table missing/invalid must not break detection
            prompt = None

    return PaneState(base.state, base.reason, base.pid, base.comm,
                     prompt, chain)


def describe(target: str) -> str:
    """One human-readable line for a pane, for logs and debugging."""
    st = pane_state(target)
    parts = [f"{target:<10} {st.state.value:<7}"]
    parts.append(f"pid={st.pid or '-'}")
    chain = " > ".join(_comm_of(p) for p in st.chain) or "-"
    parts.append(f"chain=[{chain}]")
    if st.prompt is not None:
        parts.append(f"prompt={st.prompt}")
    parts.append(f"({st.reason})")
    return "  ".join(parts)


def _comm_of(pid: int) -> str:
    st = _proc_stat(pid)
    return st["comm"] if st else "?"


def at_end(pid: int) -> bool:
    """True when `pid` is blocked reading its terminal (wants input)."""
    return classify(pid).ready
