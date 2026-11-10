"""remote.py - drive a tmux server on another machine, without running there.

Why this exists
---------------
The dashboard was local-only. Pane readiness (`termstate`) was decided by
reading `/proc`, and everything else ran `tmux ...` against the ambient server.
That makes two things impossible:

  * driving a pane on a remote host (``ssh l-portal``, ``ssh s-nodus``), and
  * driving panes that are *root's* (``sudo tmux``) from an unprivileged
    dashboard: the process state that matters belongs to root, and `/proc`
    hides it from us.

The fix is uncomfortable but small: this is *not* an agent. Nothing is
installed on the remote host, no extra channel is opened, no token is
exchanged, and no state is cached. Instead:

  * every tmux query becomes a *remote command prefix* (``ssh host tmux``,
    ``ssh host sudo tmux``, ...) executed with an argument list, never a
    stringly shell;
  * the /proc arithmetic that decides "is this pane at a prompt?" runs on the
    machine that owns the pane's processes, and only *data* comes back (stat,
    wchan, children, tty owner). The decision logic therefore stays in
    `termstate`, in one place, and remains unit-testable without any remote.

Shell quoting
-------------
A command handed to ``ssh host <string>`` is interpreted by the login shell
on the far side, so some shell strings are unavoidable. They are built here
only, from argument lists, with ``shlex.quote`` -- plus ``dq()`` for the few
fragments we *deliberately* want the shell to split (``sudo tmux``). Nothing
user-supplied reaches a shell unquoted, and tmux targets are validated.
"""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import sys
from dataclasses import dataclass, field

# Every call here is local shell builtins plus, at most, one ssh round-trip.
DEFAULT_TIMEOUT = 15


class RemoteError(RuntimeError):
    """A remote command could not be run."""


# ------------------------------------------------------------- quoting ---

def dq(text: str) -> str:
    """Double-quote for a POSIX shell, escaping only what is special.

    Single quotes were not an option: the fragments passed through here
    (``sudo -n tmux -L 'sock'``) are meant to be *split* into words by the
    remote shell, so they cannot be a single shlex-quoted token.
    """
    for ch in ("\\", '"', "`", "$"):
        text = text.replace(ch, "\\" + ch)
    return '"' + text + '"'


# tmux target syntax: session[:window[.pane]], plus %N / @N / $N ids, with
# optional trailing indicators. Anything else is rejected before it can be
# interpolated into a shell string.
_TARGET_RE = re.compile(r"^[@\$%]?[\w.-]+(:[\w.-]+(\.[\w.-]+)?)?[$!*+-]*$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_target(target: str) -> str:
    if not target or not _TARGET_RE.match(str(target)):
        raise RemoteError(f"refusing suspicious tmux target {target!r}")
    return str(target)


def validate_env_name(name: str) -> str:
    if not _ENV_NAME_RE.match(name or ""):
        raise RemoteError(f"invalid environment variable name {name!r}")
    return name


# --------------------------------------------------------------- targets ---

@dataclass(frozen=True)
class Target:
    """Where a tmux server lives, and how to reach it.

    `name`      what the user typed (``local``, ``l-portal:sudo``).
    `transport` ``local`` or ``ssh``.
    `host`      ssh destination (alias from ~/.ssh/config is fine).
    `sudo`      run tmux itself under sudo -- this is the ``sudo tmux`` pane
                case: a root-owned server, and /proc queries must be root too.
    `sudo_login` tmux stays yours, panes start ``sudo -i``.
    `socket`    ``tmux -L NAME``.
    """

    name: str = "local"
    transport: str = "local"
    host: str | None = None
    sudo: bool = False
    sudo_login: bool = False
    socket: str | None = None
    # A socket *path* rather than a name (tmux -S). Used by nixos-shell VMs
    # (/run/nixos-shell/NAME.tmux) and by any root-owned server a sudo user
    # has to reach by path; -L names cannot express those.
    socket_path: str | None = None
    extra_ssh: tuple[str, ...] = field(default_factory=tuple)

    # -- how tmux itself is invoked --------------------------------------
    def local_tmux_argv(self, *args: str) -> list[str]:
        """The argv for running tmux *on this machine*."""
        argv: list[str] = []
        if self.sudo:
            argv += sudo_words()
        argv.append("tmux")
        if self.socket_path:
            argv += ["-S", self.socket_path]
        elif self.socket:
            argv += ["-L", self.socket]
        return argv + [str(a) for a in args]

    def remote_tmux_command(self, *args: str) -> str:
        """The shell string an ssh login shell must run to reach this tmux."""
        words = " ".join(self.local_tmux_argv())  # our own literal, no input
        return words + "".join(" " + shlex.quote(str(a)) for a in args)

    def describe(self) -> str:
        """Human-readable one-liner: what the user asked for, and how reached."""
        bits = [self.name]
        if self.transport == "ssh":
            bits.append(f"via ssh {self.host}")
        if self.sudo:
            bits.append("as root")
        if self.sudo_login:
            bits.append("panes run sudo -i")
        if self.socket_path:
            bits.append(f"socket {self.socket_path}")
        elif self.socket:
            bits.append(f"socket -L {self.socket}")
        return " ".join(bits)


def sudo_words() -> list[str]:
    """``sudo`` or ``sudo -n``.

    ``-n`` (never prompt) is what a non-interactive dashboard should use: a
    pending password prompt would hang forever with no terminal to answer it.
    Cached ``sudo`` credentials from your own session still work, and a
    timestamp_timeout/``NOPASSWD`` rule works for unattended use. Opt out with
    ``DASHBOARD_SUDO_PROMPT=1`` if you really want an interactive prompt.
    """
    if os.environ.get("DASHBOARD_SUDO_PROMPT") == "1":
        return ["sudo"]
    return ["sudo", "-n"]


def parse_spec(spec: str) -> Target:
    """Parse ``[user@]host[:opt[,opt...]]`` into a Target.

    Accepted forms::

        local                       this machine, your tmux
        local:sudo                  sudo tmux here
        local:sudo-login            your tmux, panes are `sudo -i`
        l-portal                    some host over ssh
        l-portal:sudo               sudo tmux on l-portal (its pane 0.1.0)
        l-portal:sudo-login
        l-portal,sock=dbg           named tmux socket
        root@l-portal:sudo          ssh user override

    ``host`` is exactly what you would put after ``ssh`` (``~/.ssh/config``
    aliases included), so keys, jump hosts and usernames stay in ssh.
    """
    if not spec or not spec.strip():
        raise RemoteError("empty remote target")
    spec = spec.strip()

    host = spec
    opts: list[str] = []
    pos = host.find(":")
    if pos >= 0:
        host, flag_text = host[:pos], host[pos + 1:]
        opts = [o.strip() for o in flag_text.split(",") if o.strip()]
    elif "," in host:
        host, flag_text = host.split(",", 1)
        opts = [o.strip() for o in flag_text.split(",") if o.strip()]

    if not host:
        raise RemoteError(f"no host in target {spec!r}")
    if any(ch.isspace() for ch in host):
        raise RemoteError(f"no whitespace allowed in host {host!r}")

    local = host == "local"
    sudo = sudo_login = False
    socket = socket_path = None

    for opt in opts:
        if opt == "sudo":
            sudo = True
        elif opt == "sudo-login":
            sudo_login = True
        elif opt.startswith("sock="):
            value = opt.split("=", 1)[1]
            if not value:
                raise RemoteError("empty socket")
            if "/" in value:
                # A path: tmux -S. Typical for root-owned servers, e.g. the
                # nixos-shell VMs at /run/nixos-shell/NAME.tmux.
                if any(ch.isspace() for ch in value):
                    raise RemoteError(
                        f"no whitespace allowed in socket path {value!r}")
                socket_path = value
            else:
                if not _TARGET_RE.match(value):
                    raise RemoteError(f"suspicious socket name {value!r}")
                socket = value
        else:
            raise RemoteError(
                f"unknown option {opt!r} in {spec!r} "
                f"(known: sudo, sudo-login, sock=NAME or sock=/path)")

    return Target(
        name=spec,
        transport="local" if local else "ssh",
        host=None if local else host,
        sudo=sudo,
        sudo_login=sudo_login,
        socket=socket,
        socket_path=socket_path,
    )


# ------------------------------------------------------------ transports ---

class LocalTransport:
    name = "local"

    def run(self, argv, timeout=DEFAULT_TIMEOUT):
        try:
            return subprocess.run(argv, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RemoteError(
                f"command timed out after {timeout}s: {argv[0]}") from exc
        except OSError as exc:
            raise RemoteError(f"cannot run {argv[0]}: {exc}") from exc


class SshTransport:
    """One ssh round-trip per call; argument lists in, completed process out.

    ``BatchMode=yes`` is deliberate: a password or passphrase prompt cannot be
    answered by a dashboard, it can only hang. Use a key (or an already-warm
    ControlMaster socket from your own ssh config).
    """

    name = "ssh"

    def __init__(self, host: str, extra: tuple[str, ...] = ()):
        self.host = host
        self.extra = tuple(extra)

    def argv(self, remote_command: str) -> list[str]:
        return ["ssh", "-o", "BatchMode=yes", *self.extra,
                self.host, remote_command]

    def run(self, remote_command: str, timeout=DEFAULT_TIMEOUT):
        argv = self.argv(remote_command)
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RemoteError(
                f"ssh {self.host}: timed out after {timeout}s") from exc
        except OSError as exc:
            raise RemoteError(f"ssh {self.host}: {exc}") from exc
        if proc.returncode == 255:
            raise RemoteError(
                f"cannot reach {self.host} over ssh: "
                f"{proc.stderr.strip() or 'no diagnostics'}\n"
                f"  verify `ssh {self.host} true` works without prompting "
                f"(key auth, host reachable, VPN/nebula up).")
        return proc


class TargetSession:
    """A tmux server reached through a Target.

    The only two primitives are ``run_tmux`` (tmux arguments, never a shell
    string) and ``run_shell`` (a POSIX snippet that must run on the host
    owning the panes' /proc). Everything else in the dashboard is built on
    them.
    """

    def __init__(self, target: Target):
        self.target = target
        if target.transport == "ssh":
            self.transport = SshTransport(target.host or "", target.extra_ssh)
        else:
            self.transport = LocalTransport()

    # -- tmux -------------------------------------------------------------
    def run_tmux(self, *args: str, timeout: int = DEFAULT_TIMEOUT):
        if self.target.transport == "local":
            return self.transport.run(
                self.target.local_tmux_argv(*args), timeout=timeout)
        return self.transport.run(self.target.remote_tmux_command(*args),
                                  timeout=timeout)

    def tmux_ok(self, *args: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        proc = self.run_tmux(*args, timeout=timeout)
        if proc.returncode != 0:
            raise RemoteError(
                f"tmux {' '.join(args)} failed on {self.target.name}: "
                + ((proc.stderr or proc.stdout).strip() or "unknown error"))
        return proc.stdout

    def tmux_lines(self, *args: str) -> list[str]:
        out = self.tmux_ok(*args)
        return out.splitlines()

    def has_server(self) -> bool:
        return self.run_tmux("list-sessions").returncode == 0

    # -- the host that owns /proc -----------------------------------------
    def run_shell(self, script: str, timeout: int = DEFAULT_TIMEOUT):
        """Run a POSIX shell one-liner where the panes' processes live."""
        if self.target.sudo:
            # The panes belong to root. `sudo -n` fails fast instead of
            # blocking on a password prompt that can never be answered.
            argv = sudo_words() + ["sh", "-c", script]
            if self.target.transport == "local":
                return self.transport.run(argv, timeout=timeout)
            return self.transport.run(
                " ".join(shlex.quote(a) for a in argv), timeout=timeout)
        if self.target.transport == "local":
            return self.transport.run(["sh", "-c", script], timeout=timeout)
        return self.transport.run("sh -c " + shlex.quote(script),
                                  timeout=timeout)

    def run_shell_ok(self, script: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        proc = self.run_shell(script, timeout=timeout)
        if proc.returncode != 0:
            raise RemoteError(
                f"probe failed on {self.target.name}: "
                + ((proc.stderr or proc.stdout).strip() or "unknown error"))
        return proc.stdout

    # -- preflight ---------------------------------------------------------
    def check(self) -> None:
        """Raise RemoteError early, with something actionable, if unusable."""
        proc = self.run_tmux("list-sessions")
        if proc.returncode == 0:
            return
        err = (proc.stderr or proc.stdout).strip()
        low = err.lower()
        if "no server running" in low or "error connecting" in low:
            return  # reachable and empty; the dashboard will start one
        if self.target.sudo and ("sudo:" in low or "password is required" in low
                                 or "a terminal is required" in low
                                 or "not allowed" in low):
            raise RemoteError(
                f"{self.target.name}: sudo is needed to reach this tmux "
                f"server but is not available non-interactively.\n"
                f"  {err}\n"
                f"  Either configure NOPASSWD for tmux, or run the dashboard "
                f"inside a sudo shell that has cached credentials "
                f"(sudo first, then export DASHBOARD_SUDO_PROMPT=1), or set "
                f"DASHBOARD_SUDO_PROMPT=1 and run it from a terminal.")
        raise RemoteError(f"{self.target.name}: tmux is not usable: {err}")


# --------------------------------------------------------------- hostname ---

def host_identity() -> str:
    """Short hostname of *this* machine, for `expect_host` in termstate."""
    try:
        return socket.gethostname().split(".")[0]
    except Exception:  # pragma: no cover - socket is always available
        return "localhost"


def remote_host_identity(target: Target, session: "TargetSession") -> str:
    """Short hostname of the machine whose tmux we drive.

    Used as the default `expect_host`: a prompt on a remote pane must name
    the remote host, not ours, or detection would accept the local shell
    that launched an ssh session as if it were the far side.
    """
    proc = session.run_shell("hostname")
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().split(".")[0]
    # Fall back to the ssh destination's first label.
    host = (target.host or "local").split("@")[-1]
    return host.split(".")[0] if host != "local" else host_identity()


# ------------------------------------------------------------- tmux shim ---

def make_tmux_shim(target: Target, directory: str) -> str:
    """Write a ``tmux`` executable that is equivalent to the target.

    libtmux builds argv as ``[tmux_bin, ...tmux args]`` and runs it locally,
    so a remote or sudo server needs a *local* ``tmux`` that forwards. A
    short Python shim does that without touching libtmux.

    Quoting is the whole difficulty. ssh joins its arguments with single
    spaces into *one string* for the remote login shell, so ``"$@"`` does not
    survive: anything with a space re-splits, and ``$``/backticks in an
    argument expand. tmux targets and script lines contain both routinely
    (``send-keys -l 'echo $HOME'``, ``-t 'a b:0.0'``). So every argument is
    ``shlex.quote``d here and the joined string is passed to ssh as a single
    argument. The remote shell then sees exactly the words intended.

    The shim is written in Python, with the interpreter that is running the
    dashboard, because that is the one we know exists. Nothing is installed
    on the remote host: this file lives in the run's private temp dir.
    """
    argv = target.local_tmux_argv()  # e.g. ['sudo','-n','tmux','-L','x']
    if target.transport == "local" and not target.sudo:
        raise RemoteError("internal: a shim is only needed for a non-default "
                          "target")

    if target.transport == "ssh":
        script = (
            "#!" + sys.executable + "\n"
            "# generated by tmux-dashboard: reach tmux on a remote host\n"
            "import os, shlex, sys\n"
            "PREFIX = " + repr(argv) + "\n"
            "HOST = " + repr(target.host or "") + "\n"
            "remote = ' '.join([shlex.quote(p) for p in PREFIX]\n"
            "                 + [shlex.quote(a) for a in sys.argv[1:]])\n"
            "os.execvp('ssh', ['ssh', '-o', 'BatchMode=yes', HOST, remote])\n"
        )
    else:
        # Local sudo: the real tmux argv, no shell involved at all.
        script = (
            "#!" + sys.executable + "\n"
            "# generated by tmux-dashboard: reach a sudo tmux server\n"
            "import os, sys\n"
            "PREFIX = " + repr(argv) + "\n"
            "os.execvp(PREFIX[0], PREFIX + sys.argv[1:])\n"
        )
    path = os.path.join(directory, "tmux")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(script)
    os.chmod(path, 0o700)
    return path


# ------------------------------------------------------- target plumbing ---

def install(target: Target, tmpdir: str) -> "TargetSession":
    """Make `target` the server the dashboard talks to. Returns its session.

    Does three things, all of which used to be implicit "this machine, this
    user":

    1. points `compat`'s Server factory at the right tmux (shim + socket),
       which covers every libtmux call in the dashboard;
    2. points `termstate`'s tmux source at the right tmux, so pane capture,
       display-message and the /proc probe all use it;
    3. installs a ProcSource that reads the /proc of whichever user/machine
       actually owns the panes -- LocalProc when that is us, RemoteProc when
       it is root or another host.

    Deliberately no caching and no daemon: each step is a described,
    inspectable property of the current run.
    """
    import compat
    import termstate

    session = TargetSession(target)

    needs_shim = target.transport == "ssh" or target.sudo
    shim = make_tmux_shim(target, tmpdir) if needs_shim else None
    compat.set_server_target(socket_name=target.socket, tmux_bin=shim)

    class _TermstateTmux(termstate.TmuxSource):
        def run(self, *args):
            proc = session.run_tmux(*args)
            return proc.returncode, proc.stdout, proc.stderr

    termstate.set_tmux_source(_TermstateTmux())

    if target.transport == "local" and not target.sudo:
        termstate.set_proc_source(termstate.LocalProc())
    else:
        # Remote host, or root's panes: read their /proc through `session`.
        termstate.set_proc_source(termstate.RemoteProc(session))

    return session
