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
import shlex
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


# ------------------------------------------------------------ proc source ---
#
# Everything below reads /proc, but *whose* /proc depends on where the pane
# lives. Two cases break the naive `open("/proc/...")`:
#
#   * a remote host: the pane's processes are on another machine, so their
#     stat/wchan/children can only be read there;
#   * a sudo tmux: the panes are root's processes, which /proc hides from us.
#
# So all /proc access goes through a ProcSource. Two implementations exist:
# LocalProc (open files, one syscall per question) and RemoteProc (a *single*
# shell round-trip per rescan that dumps the whole table, so N panes cost one
# query rather than N*M). The classification logic above is unchanged and
# knows nothing about where the data came from.


class ProcSource:
    """The /proc of whichever user/machine owns the panes.

    `stat(pid)`  -> dict as produced by `_parse_stat`, or None
    `wchan(pid)` -> kernel wait channel, or ""
    `children(pid)` -> list of live child pids
    """

    def stat(self, pid: int) -> dict | None:  # pragma: no cover - interface
        raise NotImplementedError

    def wchan(self, pid: int) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def children(self, pid: int) -> list[int]:  # pragma: no cover - interface
        raise NotImplementedError

    def refresh(self) -> None:
        """Drop any snapshot. Called once per pane_state()."""
        return None


def _parse_stat(pid: int, raw: str) -> dict | None:
    """Parse /proc/<pid>/stat. comm is parenthesised and may contain spaces."""
    raw = raw.strip()
    if not raw:
        return None
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
        # fields 4.. : state ppid pgrp session tty_nr tpgid ...
        # rest[1]=ppid, rest[5]=tpgid, rest[11]=utime, rest[12]=stime
        "ppid": int(rest[1]),
        "tpgid": int(rest[5]),
        "utime": int(rest[11]),
        "stime": int(rest[12]),
    }


def _clean_wchan(raw: str) -> str:
    """poll_schedule_timeout.constprop.0 -> poll_schedule_timeout"""
    return (raw or "").strip().split(".", 1)[0]


class LocalProc(ProcSource):
    """This process's /proc, read directly."""

    def stat(self, pid: int) -> dict | None:
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8",
                      errors="replace") as fh:
                raw = fh.read()
        except OSError:
            return None
        return _parse_stat(pid, raw)

    def wchan(self, pid: int) -> str:
        try:
            with open(f"/proc/{pid}/wchan", "r", encoding="utf-8",
                      errors="replace") as fh:
                return _clean_wchan(fh.read())
        except OSError:
            return ""

    def children(self, pid: int) -> list[int]:
        kids: list[int] = []
        try:
            entries = os.listdir("/proc")
        except OSError:
            return kids
        for entry in entries:
            if not entry.isdigit():
                continue
            st = self.stat(int(entry))
            if st and st["ppid"] == pid:
                kids.append(int(entry))
        return kids


class RemoteProc(ProcSource):
    """The /proc of a remote host or of root, via one shell round-trip.

    `/proc` cannot be read remotely one syscall at a time, so a snapshot of
    the whole process table is taken and parsed here. It is refreshed on each
    `pane_state()` call, which is what `rescan` means.

    Snapshots are only taken when they are needed, and a failure (host gone,
    sudo refused) degrades to "no data" -- the caller then falls back to the
    on-screen prompt check, exactly as it does on a local pane whose process
    vanished.
    """

    # One round-trip that dumps everything classify() can ask about:
    #   pid|<whole /proc/pid/stat line>
    # then
    #   @@WCHAN
    #   pid|<wchan>
    # Two loops rather than one so a transient /proc race cannot misalign the
    # stat text with a different pid's wchan.
    SCRIPT = r"""
for d in /proc/[0-9]*; do
  p=${d#/proc/}
  { read -r line < "$d/stat"; } 2>/dev/null || continue
  printf '%s|%s\n' "$p" "$line"
done
echo '@@WCHAN'
for d in /proc/[0-9]*; do
  p=${d#/proc/}
  printf '%s|' "$p"
  cat "$d/wchan" 2>/dev/null
  echo
done
"""

    def __init__(self, session, debugging: bool = False):
        """`session` is a remote.TargetSession."""
        self.session = session
        self.debugging = debugging
        self._stats: dict[int, dict] = {}
        self._wchans: dict[int, str] = {}
        self._snapshotted = False
        self.last_error: str | None = None

    def refresh(self) -> None:
        self._snapshotted = False
        self._stats.clear()
        self._wchans.clear()
        self.last_error = None

    def _snapshot(self) -> None:
        if self._snapshotted:
            return
        self._snapshotted = True
        try:
            out = self.session.run_shell_ok(self.SCRIPT, timeout=20)
        except Exception as exc:  # RemoteError or anything transport-y
            self.last_error = str(exc)
            if self.debugging:
                print(f"{{RemoteProc}} snapshot failed: {exc}")
            return

        mode = "stat"
        for line in out.splitlines():
            if line.strip() == "@@WCHAN":
                mode = "wchan"
                continue
            if not line or "|" not in line:
                continue
            pid_text, _, rest = line.partition("|")
            if not pid_text.isdigit():
                continue
            pid = int(pid_text)
            if mode == "stat":
                st = _parse_stat(pid, rest)
                if st is not None:
                    self._stats[pid] = st
            else:
                self._wchans[pid] = _clean_wchan(rest)

    def stat(self, pid: int) -> dict | None:
        self._snapshot()
        return self._stats.get(pid)

    def wchan(self, pid: int) -> str:
        self._snapshot()
        return self._wchans.get(pid, "")

    def children(self, pid: int) -> list[int]:
        self._snapshot()
        return [p for p, st in self._stats.items() if st["ppid"] == pid]


# The source every helper below uses. LocalProc unless a caller installs a
# RemoteProc (see main_tdashboard.connect_server / remote.py).
_proc: ProcSource = LocalProc()


def set_proc_source(source: ProcSource) -> None:
    """Install the /proc view used by `classify` and friends."""
    global _proc
    _proc = source


def proc_source() -> ProcSource:
    return _proc


def _proc_stat(pid: int) -> dict | None:
    return _proc.stat(pid)


def _wchan(pid: int) -> str:
    return _proc.wchan(pid)


def _children(pid: int) -> list[int]:
    return _proc.children(pid)


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


class TmuxSource:
    """How to talk to the tmux server holding the pane under inspection.

    Defaults to the ambient one (``tmux`` on $PATH, this user). A remote or
    sudo target replaces it with a wrapper around remote.TargetSession, which
    may mean an ssh round-trip -- so callers must keep the number of calls
    small (see `PaneInfo` below: one display-message, one capture-pane).
    """

    def run(self, *args: str):
        """Return (returncode, stdout, stderr) for a tmux invocation."""
        try:
            proc = subprocess.run(["tmux", *[str(a) for a in args]],
                                  capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, "", str(exc)
        return proc.returncode, proc.stdout, proc.stderr


_tmux: TmuxSource = TmuxSource()


def set_tmux_source(source: TmuxSource) -> None:
    global _tmux
    _tmux = source


def tmux_source() -> TmuxSource:
    return _tmux


def capture(target: str, scroll: int = 0) -> str:
    """Capture a pane's visible (or scrolled-back) text."""
    target = _safe_target(target)
    args = ["capture-pane", "-p", "-t", target]
    if scroll:
        args += ["-S", f"-{scroll}"]
    rc, out, _ = _tmux.run(*args)
    return out if rc == 0 else ""


def _safe_target(target: str) -> str:
    """Reject targets that would be interpreted as shell inside an ssh string."""
    text = str(target)
    if any(ch.isspace() for ch in text) or text.startswith("-"):
        raise ValueError(f"refusing suspicious tmux target {text!r}")
    return text


# The pane facts pane_state needs, fetched in ONE tmux round-trip. On a
# remote target each call is an ssh handshake otherwise.
PANE_FORMAT = "\t".join((
    "#{pane_pid}",
    "#{pane_tty}",
    "#{pane_current_command}",
    "#{pane_width}",
    "#{pane_height}",
))


@dataclass(frozen=True)
class PaneInfo:
    target: str
    pid: int
    tty: str
    command: str
    width: int
    height: int


def pane_info(target: str) -> PaneInfo | None:
    """Ask tmux about a pane. Returns None if the pane does not exist."""
    target = _safe_target(target)
    rc, out, _ = _tmux.run("display-message", "-p", "-t", target, PANE_FORMAT)
    if rc != 0:
        return None
    fields = out.rstrip("\n").split("\t")
    if len(fields) < 5:
        return None
    try:
        pid = int(fields[0])
    except ValueError:
        return None

    def _int(text):
        try:
            return int(text)
        except ValueError:
            return 0

    return PaneInfo(target=target, pid=pid, tty=fields[1],
                    command=fields[2], width=_int(fields[3]),
                    height=_int(fields[4]))


# Programs that *host* another terminal rather than being one. A pane running
# one of these has its foreground process blocked on the tty for its whole
# lifetime, so the process-state signal says "READY" even while the thing
# inside is booting, at a login prompt, or running a command.
TERMINAL_HOSTS = ("qemu-system", "qemu-kvm", "virt-viewer", "virsh",
                  "minicom", "picocom", "screen", "tmux", "socat")


def _is_terminal_host(comm: str | None) -> bool:
    if not comm:
        return False
    # Nix truncates long program names to `.<first 15 chars>` (".qemu-system-x8"),
    # so match on the basename after any leading dot.
    name = comm.lstrip(".")
    return any(name.startswith(h) for h in TERMINAL_HOSTS)


# Programs that take over the tty to page through text: `git log`, `man`, a
# `--help` that is longer than the screen. They *are* blocked reading the tty,
# so process state alone reports READY -- but a shell command typed into one is
# not run: `less` treats it as a search or a motion, and the caller's command
# silently disappears into the pager. That is the same "looks ready, is not a
# shell" hazard as a REPL or a password prompt, so a pager is reported as an
# *unsafe* prompt rather than as readiness.
#
# Matched on the process that owns the tty, so it works regardless of what the
# screen happens to show: `git log` fresh in `less` sits at the top of the log
# with no `--More--` or `:` yet, which the screen table's `pager` entry misses.
PAGERS = ("less", "more", "most", "pg", "moar", "pager")


def _is_pager(comm: str | None) -> bool:
    if not comm:
        return False
    name = comm.lstrip(".")
    return any(name == p or name.startswith(p + "-") or name.startswith(p + ".")
               for p in PAGERS)


# Output a launcher leaves behind when it is interrupted before it starts the
# thing it was going to start. `nixos-shell` prints the first; the rest are the
# generic "the command never ran" forms.
# The line a caller types to start the launcher. An exit marker older than the
# most recent one of these belongs to a previous run.
LAUNCH_LINES = ("nixos-shell ", "nix-shell ", "vagrant up", "qemu-system")

LAUNCHER_EXIT_MARKERS = (
    "error: interrupted by the user",
    "error: killed by signal",
)


def launcher_exited(target: str, scroll: int = 60) -> str | None:
    """The launcher's exit line if it died before starting, else None.

    A pane whose foreground program returns to the shell is not necessarily
    "ready": for a launcher like `nixos-shell` it means the guest was never
    started, or was torn down. Every detection path in this module answers
    "is the foreground program blocked reading the terminal", which is equally
    true of the idle shell left behind -- so a crashed run reported READY, and
    a caller waiting for the guest waited out its whole timeout against a
    process that no longer existed.

    Measured 2026-11-12: Ctrl-C in the HAT pane printed
    `error: interrupted by the user`, `start cobalt` polled for 1500 s, and the
    pane reported `READY ... chain=[zsh]` throughout.

    Returning the marker (rather than a bool) lets the caller quote it.
    """
    text = capture(target, scroll=scroll)
    for marker in LAUNCHER_EXIT_MARKERS:
        if marker not in text:
            continue
        # Only a marker that comes AFTER the last launch line counts. A dead run
        # leaves its message in scrollback, and a later `start` reuses the same
        # pane, so a plain substring search reported the previous run's
        # interruption against the new one -- measured 2026-11-12 with `state`
        # while a fresh build was running.
        last_marker = text.rfind(marker)
        last_launch = max(
            (text.rfind(line) for line in LAUNCH_LINES), default=-1)
        if last_marker > last_launch:
            return marker
    return None


def is_terminal_host(target: str) -> bool:
    """True when the pane's foreground program hosts another terminal.

    Such a pane needs the screen to decide readiness; everything else is
    answered by process state. Cheap enough to call before capturing
    (one tmux query), and the caller needs to know in order to avoid sending a
    probe keystroke into an ordinary shell pane.

    The answer comes from the `/proc` chain, not from tmux's
    `pane_current_command`: tmux reports the shell the pane was *created* with,
    not what is running in it. Measured 2026-11-11 on the HAT cobalt fixture, a
    pane whose chain was `zsh > .nixos-shell-wr > .qemu-system-x8` reported
    `pane_current_command=bash`. Since this predicate gates the redraw probe,
    the guest prompt was never looked for, `at_end` always answered False, and
    `scripts/hat-isp.py core cobalt` reported FAIL on a guest that was sitting
    at `root@isp-cobalt:~/github/network-site-esp/ >` the whole time.

    `pane_state` already computes the chain (and already uses it for
    `describe`), so this asks the same source rather than adding a second,
    disagreeing one.
    """
    state = pane_state(target)
    if _is_terminal_host(state.comm):
        return True
    # A wrapper (`.nixos-shell-wr`) can sit *above* the terminal host, so the
    # deepest comm alone is not enough; scan the whole ancestry.
    return any(_is_terminal_host(_comm_of(pid)) for pid in state.chain)


def pane_state(target: str, rescan: bool = True, expect_host: str | None = None,
               after: str | None = None, stable: bool | None = None) -> PaneState:
    """Classify a tmux pane target (session:window.pane).

    Two independent signals are combined:

    1. Process state (`classify`) - is the tty owner blocked reading? This is
       prompt-agnostic and, for an ordinary shell pane, the primary signal.
    2. The prompt table (`prompts.py`) - what the *screen* shows is asking.

    For a pane that hosts another terminal (QEMU's serial console, `screen`,
    `minicom`, ...) signal 1 is worthless: the host program is parked on the
    tty forever, so it would report READY during a guest's boot, at its login
    prompt, and while it runs a command. In that case the screen decides, and
    process state is only used when the screen agrees there is a prompt.

    `expect_host` requires the matched prompt line to mention that host name.
    It exists to stop a *launching* shell's prompt ("[nix-shell:~/repo]$") from
    being mistaken for the guest's prompt while the guest is still starting.

    `after` restricts the judgement to text following the last occurrence of
    that marker, so a prompt from before a command cannot make the command
    look finished.

    `rescan` matters because prompts nest: `msf6 >` -> `meterpreter >` ->
    `C:\\>`. Each time the process chain grows or shrinks, the prompt that is
    actually waiting for input changes, so the match is redone from scratch
    rather than cached.

    `stable`, when given, is a caller-supplied answer to "does a bare Enter
    leave this pane looking the same?" (see main_tdashboard._stable_prompt).
    It is the only way to know that a *terminal host* is at a prompt, since
    such a program is blocked on the tty for its whole life. When it is True
    the screen is trusted enough to learn an unknown prompt from, which is how
    a guest's prompt stops needing a regex in prompts.txt.
    """
    # A fresh snapshot per call is what `rescan` means; RemoteProc uses it to
    # avoid one ssh round-trip per pid.
    if rescan:
        _proc.refresh()

    info = pane_info(target)
    if info is None:
        return PaneState(State.UNKNOWN, f"no such pane {target!r}")
    shell_pid = info.pid

    chain = tuple(process_chain(shell_pid)) if rescan else (shell_pid,)
    owner = _pane_tty_owner(shell_pid) or chain[-1] if chain else shell_pid
    base = classify(owner)

    # A pager sitting on the tty is blocked reading it, so `classify` says
    # READY -- but it is not a shell. Report it as an unsafe prompt (kind
    # "menu") so `at_end`/`wait_pane_idle` refuse to type a command line into
    # it, and so `describe` says *why*. This is process-based, so it fires even
    # when the screen shows the top of a page with no `--More--` yet.
    if _is_pager(base.comm):
        match = None
        try:
            import prompts as _prompts
            tail = ""
            if rescan:
                tail = _prompts.last_line(
                    _prompts.strip_console_noise(capture(target)))
            match = _prompts.PromptMatch("pager", "menu", tail, 0, owner)
        except Exception:
            # prompts.txt missing/invalid must not break detection.
            match = None
        return PaneState(
            State.BUSY,
            f"{base.comm} is a pager; not a shell (quit it before sending)",
            base.pid, base.comm, match, chain,
        )

    # Prompt match, tagged with the depth of the process that owns the tty so
    # a nested prompt is distinguishable from the outer one.
    prompt = None
    screen = None
    if rescan:
        try:
            import prompts as _prompts
            depth = chain.index(owner) if owner in chain else len(chain) - 1
            screen = capture(target)
            prompt = _prompts.match_screen(screen, depth=depth,
                                           pid=owner, after=after)
            # Learn the prompt instead of requiring it to be in a table.
            #
            # The evidence has to come from the two places that can know a
            # pane is "waiting for input" without recognising the prompt:
            #
            #   * process state READY -- true for ordinary shells/REPLs;
            #   * a terminal host (QEMU's console, screen, a nested tmux),
            #     whose process is *always* blocked on the tty, so its screen
            #     must be redraw-stable instead (`stable`).
            #
            # In both cases the last line of the screen is what the program is
            # asking with. Learning it is what lets an unknown prompt (a
            # themed shell, a guest's PS1) be recognised next time; without it
            # a terminal-host pane with an unknown prompt could never be ready.
            if screen and (base.state is State.READY or stable):
                last = _prompts.last_line(_prompts.strip_console_noise(screen))
                if last:
                    # A redraw-stable screen is stronger evidence than
                    # repeated observation: it has already been shown to
                    # survive an empty Enter, so trust it immediately.
                    # Process-state READY alone is weaker, because a command's
                    # final output line also sits under a ready shell, so that
                    # needs a second sighting (prompts.LEARN_AFTER).
                    threshold = 1 if stable else None
                    if prompt is None:
                        _prompts.learn(last, threshold=threshold)
                        # Re-match: this call's own observation may have just
                        # been promoted, and returning "busy" on the sampling
                        # pass that *proved* the prompt would make every
                        # first look at a new prompt fail for no reason.
                        prompt = _prompts.match_learned(last, depth=depth,
                                                        pid=owner)
                    else:
                        # Refine even a table hit, so the *actual* prompt text
                        # (host, theme, timestamp shape) is matched next time
                        # rather than the generic guess that happened to fit.
                        _prompts.learn(last, tool=prompt.tool,
                                       kind=prompt.kind, threshold=threshold)
        except Exception:  # table missing/invalid must not break detection
            prompt = None

    # The /proc of this pane's processes could not be read (ssh dropped, sudo
    # refused). Fall back to the on-screen prompt -- the same signal used for
    # panes hosting another terminal -- and say so in the reason, because this
    # is strictly weaker: a pane running a silent reader looks busy.
    if base.state is State.UNKNOWN and base.reason.startswith("no such process"):
        why = getattr(_proc, "last_error", None)
        if screen is not None and prompt is not None:
            if not prompt.safe_to_send:
                return PaneState(State.BUSY,
                                 f"unsafe prompt (no /proc: {why}): {prompt}",
                                 base.pid, base.comm, prompt, chain)
            return PaneState(State.READY,
                             f"prompt only (no /proc: {why}): {prompt}",
                             base.pid, base.comm, prompt, chain)
        return PaneState(
            State.UNKNOWN,
            f"cannot read the pane's process state ({why}); "
            f"install the dashboard on the remote host for reliable "
            f"detection, or use `# wait_untill=` directives",
            base.pid, base.comm, prompt, chain)

    # A prompt belongs to the wrong host: the pane is showing the shell that
    # launched the guest, not the guest. That is not readiness.
    if prompt is not None and expect_host and expect_host not in prompt.line:
        return PaneState(
            State.BUSY,
            f"prompt does not belong to {expect_host!r}: {prompt.line!r}",
            prompt.pid, prompt.tool, None, chain,
        )

    # A prompt whose host was requested and matched (expect_host given and
    # present above) is definitive, whatever the process state says: the
    # screen is showing the prompt of the thing we are driving.
    if prompt is not None and expect_host and expect_host in prompt.line:
        if not prompt.safe_to_send:
            return PaneState(State.BUSY, f"unsafe prompt: {prompt}",
                             base.pid, base.comm, prompt, chain)
        return PaneState(State.READY, f"prompt for {expect_host!r}: {prompt}",
                         base.pid, base.comm, prompt, chain)

    # Terminals hosted in a pane invert the usual priority: the host process is
    # permanently blocked on the tty, so only the screen can say whether the
    # thing inside is at a prompt.
    if _is_terminal_host(base.comm):
        if prompt is None:
            return PaneState(
                State.BUSY,
                f"{base.comm} hosts a terminal; no prompt on screen",
                base.pid, base.comm, None, chain,
            )
        if not prompt.safe_to_send:
            return PaneState(State.BUSY, f"unsafe prompt: {prompt}",
                             base.pid, base.comm, prompt, chain)
        return PaneState(State.READY, f"on-screen prompt: {prompt}",
                         base.pid, base.comm, prompt, chain)

    return PaneState(base.state, base.reason, base.pid, base.comm,
                     prompt, chain)


def describe(target: str, **kwargs) -> str:
    """One human-readable line for a pane, for logs and debugging."""
    st = pane_state(target, **kwargs)
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
