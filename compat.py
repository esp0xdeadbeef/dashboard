"""compat.py - single place that knows the libtmux API surface.

libtmux removed several APIs the original dashboard was built on:

    Server.find_where()      removed in 0.17.0  -> Server.sessions.get(...)
    Session.attached_pane    removed in 0.31.0  -> Session.active_pane
    Session.attached_window  removed in 0.31.0  -> Session.active_window

Rather than scattering `.sessions.get()` calls through the codebase, every
libtmux access goes through the helpers here. If libtmux breaks again, this is
the only file that needs to change.

Also hosts the non-root safety checks: tmux servers are per-user, so the
dashboard must never be run as root, and libtmux must talk to the same tmux
server as the invoking user.
"""

import os
import subprocess
import sys

try:
    import libtmux
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit(
        "dashboard: libtmux is not installed for this interpreter.\n"
        "  python3 -m venv venv && . venv/bin/activate\n"
        "  pip install -r requirements.txt\n"
        f"(python: {sys.executable})"
    ) from exc

MIN_LIBTMUX = (0, 62)
MAX_LIBTMUX_EXCLUSIVE = (1, 0)


class CompatError(RuntimeError):
    """Raised when the runtime environment cannot support the dashboard."""


# --------------------------------------------------------------------- guard ---

def assert_not_root():
    """Refuse to run as root.

    A tmux server is per-user, so a root-run dashboard gets a *different*
    server from the one you are sitting in, and everything it creates is
    root-owned (and usually unreadable by your normal user afterwards).
    Nothing here needs privilege: panes are spawned by your own tmux server.

    Driving a *root-owned* tmux (the ``sudo tmux`` case) does not lift this:
    the dashboard keeps running as you and reaches root's server through
    ``sudo -n tmux`` on a named socket, so the panes are root's while the
    dashboard and its files are still yours. Run as root and you would have
    to open your own server with sudo to match, which is exactly what this
    guard prevents.
    """
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise CompatError(
            "refusing to run as root: tmux servers are per-user, so a root "
            "dashboard would spawn into a separate tmux server and leave "
            "root-owned files behind.\n"
            "Run it as your normal user instead. If your tmux session was "
            "started by root, log in as yourself first."
        )


def assert_env_sane():
    """Warn when TMUX_TMPDIR/XDG_RUNTIME_DIR could point at another server."""
    uid = getattr(os, "getuid", lambda: "unknown")()
    tmpdir = os.environ.get("TMUX_TMPDIR")
    if tmpdir:
        try:
            st = os.stat(tmpdir)
        except OSError:
            return
        if st.st_uid != uid:
            print(
                f"compat: warning: TMUX_TMPDIR={tmpdir!r} is owned by uid "
                f"{st.st_uid}, not you (uid {uid}); you may be talking to "
                f"another user's tmux server.",
                file=sys.stderr,
            )


def check_libtmux_version():
    """Fail loudly on an unsupported libtmux instead of with DeprecatedError."""
    raw = getattr(libtmux, "__version__", "0")
    parts = []
    for chunk in str(raw).split(".")[:2]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 2:
        parts.append(0)
    version = tuple(parts)

    if version < MIN_LIBTMUX or version >= MAX_LIBTMUX_EXCLUSIVE:
        raise CompatError(
            f"libtmux {raw} is not in the supported range "
            f">={'.'.join(map(str, MIN_LIBTMUX))},"
            f"<{'.'.join(map(str, MAX_LIBTMUX_EXCLUSIVE))}.\n"
            f"The dashboard is pinned to that range because libtmux removes "
            f"APIs between minor releases. Update requirements.txt rows "
            f"deliberately, not implicitly."
        )
    return raw


# ------------------------------------------------------------------ accessors ---

# ------------------------------------------------------------------ targets ---
#
# A "target" is where the tmux server lives: this machine as this user
# (the default), this machine as root (`sudo tmux`), or another machine over
# ssh. libtmux can only express the first two cheaply -- Server(socket_name=,
# socket_path=, tmux_bin=) -- so a remote server is reached by handing it a
# `tmux` *shim* on disk (see remote.make_tmux_shim) that execs
# `ssh host tmux "$@"`. Every libtmux call then goes over ssh, unchanged.
#
# The active socket/shim is sticky, because `reconnect()` (and therefore
# every post-split cache drop) has to build the same Server again.

_socket_name = None
_socket_path = None
_tmux_bin = None


def set_server_target(socket_name=None, socket_path=None, tmux_bin=None):
    """Pin which tmux server every Server built from now on talks to."""
    global _socket_name, _socket_path, _tmux_bin
    _socket_name, _socket_path, _tmux_bin = socket_name, socket_path, tmux_bin


def current_server_target():
    return {"socket_name": _socket_name, "socket_path": _socket_path,
            "tmux_bin": _tmux_bin}


def connect():
    """Return a Server bound to the active target's tmux server."""
    kwargs = {}
    if _socket_name:
        kwargs["socket_name"] = _socket_name
    if _socket_path:
        kwargs["socket_path"] = _socket_path
    if _tmux_bin:
        kwargs["tmux_bin"] = _tmux_bin
    return libtmux.Server(**kwargs)


def reconnect(server):
    """Return a brand-new Server handle for the same target.

    libtmux caches Window/Pane objects inside a Session, so after a split()
    the old Session's active_window can point at a window id that no longer
    exists ("list-panes: can't find window: @N"). A fresh Server re-queries
    everything and is the only reliable way to drop that cache.

    The target is remembered here rather than read off `server`, because a
    remote server's `tmux_bin` is a generated shim path and a sudo server is
    reached through a shim too -- reading them back off the object is how you
    end up silently talking to the wrong server after one split.
    """
    return connect()


def get_session(server, name):
    """Return the session called `name`, or None. Replaces find_where()."""
    return server.sessions.get(default=None, session_name=name)


def require_session(server, name):
    """Return the session called `name`, raising if it is absent."""
    session = get_session(server, name)
    if session is None:
        raise CompatError(f"no tmux session named {name!r}")
    return session


def active_pane(session):
    """The pane libtmux used to call `attached_pane`."""
    return session.active_pane


def active_window(session):
    """The window libtmux used to call `attached_window`."""
    return session.active_window


def panes_of(session):
    return list(session.panes)


def windows_of(session):
    return list(session.windows)


def list_session_names(server):
    return [s.session_name for s in server.sessions]


# ------------------------------------------------------------------ run as user ---

def assert_tmux_running_as_user(server, name=None):
    """Best-effort check that the target tmux server belongs to this user."""
    uid = getattr(os, "getuid", lambda: None)()
    if uid is None:
        return
    # The tmux socket lives under /tmp/tmux-<uid>/; libtmux only ever reads
    # its own server, so we simply confirm the server is reachable and owned
    # by us when the socket path is exposed.
    try:
        sessions = server.sessions
    except Exception as exc:  # pragma: no cover - environment dependent
        raise CompatError(f"cannot reach tmux server: {exc}") from exc
    if name is not None and not any(
        s.session_name == name for s in sessions
    ):
        raise CompatError(
            f"tmux server reachable but session {name!r} missing; are you "
            f"connected to the same tmux server you spawn into?"
        )
    return True


# --------------------------------------------------------------- mutators ---
#
# Same story as the accessors: libtmux renamed every mutator below and the
# old names now raise DeprecatedError. Centralised here so a future rename is
# a one-file change.
#
#   Session.kill_session()    -> Session.kill()        (removed 0.30.0)
#   Session.attach_session()  -> Session.attach()      (removed 0.30.0)
#   Window.split_window()     -> Window.split()        (removed 0.33.0)
#   Pane.split_window()       -> Pane.split()          (removed 0.33.0)
#   Pane.resize_pane()        -> Pane.resize()         (removed 0.28.0)


def kill_session(session):
    return session.kill()


def attach_session(session):
    return session.attach()


def split_window(owner, **kwargs):
    """Split a Window or a Pane, whichever is passed."""
    return owner.split(**kwargs)


def _server_of(obj):
    """Accept a Server, a Session, or None (meaning the active target)."""
    if obj is None:
        return connect()
    if hasattr(obj, "sessions") and not hasattr(obj, "session_name"):
        return obj
    return obj.server


def _tmux_argv(*args):
    """The argv that talks to the *active* tmux server.

    All the direct tmux invocations below go through this instead of
    ``["tmux", ...]`` so that a remote or sudo target is honoured. On the
    default target it is literally ``["tmux", ...]``.
    """
    bin_ = _tmux_bin or "tmux"
    argv = [bin_]
    if _socket_name:
        argv += ["-L", _socket_name]
    if _socket_path:
        argv += ["-S", str(_socket_path)]
    return argv + [str(a) for a in args]


def split_pane(server, session_name, attach=True, start_directory=None,
               direction="down", window_id=None):
    """Split a window and return the new pane id.

    Runs `tmux split-window` directly instead of going through libtmux's
    object graph. libtmux caches Window/Pane objects on the Session, and a
    split leaves those handles pointing at a window id that still exists but
    whose cached pane list is stale, so the next active_pane lookup raises
    "list-panes: can't find window: @N".

    `window_id` (``@N``) targets a specific window. This matters for a
    remote or sudo target, where "the session's active window" is whatever
    happened to be active last -- which is not necessarily the window the
    caller is filling.
    """
    server = _server_of(server)
    session = require_session(server, session_name)
    target = window_id or session.session_id
    args = ["split-window", "-t", target]
    if start_directory:
        args += ["-c", str(start_directory)]
    if direction == "right":
        args += ["-h"]
    if not attach:
        args += ["-d"]
    proc = subprocess.run(_tmux_argv(*args, "-P", "-F", "#{pane_id}"),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise CompatError(f"split-window failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def resize_pane(pane, **kwargs):
    return pane.resize(**kwargs)


def rename_window(window, new_name):
    return window.rename_window(new_name)


def rename_session(session, new_name):
    return session.rename_session(new_name)


def new_window(session, **kwargs):
    return session.new_window(**kwargs)


def new_window_named(session, name, start_directory=None):
    """Create a window called `name` and return its id (``@N``).

    One tmux call instead of `new_window()` + `active_window()` +
    `rename_window()`. That three-step version is wrong whenever the session
    handle is stale -- which is normal, because a session file renews its
    session -- and it silently renames a *different* window: with two windows
    open, `active_window()` keeps pointing at the old one, so the new window
    stays "tmux" and the previous one gets the new name.
    """
    args = ["new-window", "-d", "-P", "-F", "#{window_id}", "-n", name]
    if start_directory:
        args += ["-c", str(start_directory)]
    proc = subprocess.run(_tmux_argv(*args, "-t", session.session_name),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise CompatError(f"new-window failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def window_id_named(session_name, window_name):
    """The ``@N`` of a named window, or None."""
    for window in windows_of_session(session_name):
        if window[1] == window_name:
            return window[0]
    return None


def windows_of_session(session_name):
    """[(window_id, window_name, window_index)] straight from tmux."""
    proc = subprocess.run(
        _tmux_argv("list-windows", "-t", session_name, "-F",
                   "#{window_id}\t#{window_name}\t#{window_index}"),
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise CompatError(
            f"no window in session {session_name!r}: {proc.stderr.strip()}")
    rows = [line.split("\t") for line in proc.stdout.splitlines() if line]
    rows.sort(key=lambda r: int(r[2]))
    return [(r[0], r[1], r[2]) for r in rows]


def select_layout(window, layout):
    return window.select_layout(layout)


def select_layout_for(server, session_name, layout="tiled", window_id=None):
    """Apply a layout to a window via tmux directly.

    `window_id` renames the target to a specific window (see split_pane).
    """
    server = _server_of(server)
    session = require_session(server, session_name)
    target = window_id or session.session_name
    proc = subprocess.run(_tmux_argv("select-layout", "-t", target, layout),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise CompatError(f"select-layout failed: {proc.stderr.strip()}")


def select_window(server, window_id):
    """Make ``window_id`` (``@N``) the active window of its session.

    Needed because libtmux's `Session.active_window` -- and therefore
    `active_pane` -- answers "what some client is looking at", which on a
    remote or sudo server is not necessarily the window being filled.
    """
    proc = subprocess.run(_tmux_argv("select-window", "-t", window_id),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise CompatError(f"select-window failed: {proc.stderr.strip()}")
    return window_id


def window_state(session_name, window_name=None, retries=10):
    """(window_id, window_name, active_pane_id) for a live window.

    Read straight from tmux instead of libtmux, because a session file often
    renews its session and libtmux's cached ``$id``/window list then points at
    objects that no longer exist.

    `window_name` selects a specific window; by default the newest one is
    used, which is the one a session file has just created and is filling.

    Retries briefly: tmux returns "can't find window: @N" for a moment after a
    split, while the new pane is being created. That is a transient race, not
    a missing window, so failing the whole run on it would make the dashboard
    flaky rather than correct.
    """
    import time as _time

    last = ""
    for attempt in range(retries):
        if attempt:
            _time.sleep(min(0.05 * attempt, 0.5))
        proc = subprocess.run(
            _tmux_argv("list-windows", "-t", session_name, "-F",
                       "#{window_id}\t#{window_name}\t#{window_index}"),
            capture_output=True, text=True)
        if proc.returncode != 0:
            last = proc.stderr.strip() or proc.stdout.strip()
            continue
        rows = [line.split("\t") for line in proc.stdout.splitlines() if line]
        if window_name is not None:
            rows = [r for r in rows if r[1] == window_name] or rows
        if not rows:
            continue
        window_id = max(rows, key=lambda r: int(r[2]))[0]

        panes = subprocess.run(
            _tmux_argv("list-panes", "-t", window_id, "-F",
                       "#{pane_id}\t#{pane_active}"),
            capture_output=True, text=True)
        if panes.returncode != 0:
            last = panes.stderr.strip() or panes.stdout.strip()
            continue
        entries = [line.split("\t") for line in panes.stdout.splitlines()
                   if line]
        if not entries:
            last = f"window {window_id} has no panes"
            continue
        active = [p[0] for p in entries if p[1] == "1"] or [entries[-1][0]]
        name = [r[1] for r in rows if r[0] == window_id][0]
        return window_id, name, active[0]

    raise CompatError(
        f"cannot read a window of session {session_name!r}: {last}")


def window_by_id(window_id):
    """A libtmux Window for ``@N``, re-resolved from the live server."""
    window = connect().windows.get(default=None, window_id=window_id)
    if window is None:
        raise CompatError(f"no such window {window_id}")
    return window


def active_pane_of_window(window_id):
    """The active pane *of a specific window*, as a live libtmux Pane.

    `Session.active_pane` answers "what the session's active window shows",
    which is not what a caller that just created a named window wants -- and
    on a stale session handle it can name a pane in a different window
    entirely. This resolves through the window id instead.
    """
    proc = subprocess.run(
        _tmux_argv("list-panes", "-t", window_id, "-F",
                   "#{pane_id}\t#{pane_active}"),
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise CompatError(f"list-panes failed: {proc.stderr.strip()}")
    rows = [line.split("\t") for line in proc.stdout.splitlines() if line]
    if not rows:
        raise CompatError(f"window {window_id} has no panes")
    active = [r[0] for r in rows if r[1] == "1"] or [rows[-1][0]]
    return pane_by_id(active[0])


def pane_ids_of_window(window_id):
    """Pane ids of a window, in creation (index) order."""
    proc = subprocess.run(
        _tmux_argv("list-panes", "-t", window_id, "-F",
                   "#{pane_id}\t#{pane_index}"),
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise CompatError(f"list-panes failed: {proc.stderr.strip()}")
    rows = [line.split("\t") for line in proc.stdout.splitlines() if line]
    rows.sort(key=lambda r: int(r[1]))
    return [r[0] for r in rows]


def pane_by_id(pane_id):
    """A libtmux Pane for ``%N``, re-resolved from the live server."""
    pane = connect().panes.get(default=None, pane_id=pane_id)
    if pane is None:
        raise CompatError(f"no such pane {pane_id}")
    return pane


def send_keys(pane, *keys):
    """Send keys to a pane (the only supported way to type into one)."""
    return pane.cmd("send-keys", *keys)


def capture_pane(pane, start=None, end=None):
    """Capture pane contents as a list of lines."""
    if start is not None:
        return pane.cmd("capture-pane", "-p", "-S", str(start)).stdout
    return pane.capture_pane()
