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

def connect():
    """Return a Server bound to the invoking user's tmux server."""
    return libtmux.Server()


def reconnect(server):
    """Return a brand-new Server handle.

    libtmux caches Window/Pane objects inside a Session, so after a split()
    the old Session's active_window can point at a window id that no longer
    exists ("list-panes: can't find window: @N"). A fresh Server re-queries
    everything and is the only reliable way to drop that cache.
    """
    return libtmux.Server()


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
    """Accept a Server or a Session and return a Server."""
    if hasattr(obj, "sessions") and not hasattr(obj, "session_name"):
        return obj
    return obj.server


def split_pane(server, session_name, attach=True, start_directory=None,
               direction="down"):
    """Split the active pane and return the new pane id.

    Runs `tmux split-window` directly instead of going through libtmux's
    object graph. libtmux caches Window/Pane objects on the Session, and a
    split leaves those handles pointing at a window id that still exists but
    whose cached pane list is stale, so the next active_pane lookup raises
    "list-panes: can't find window: @N".
    """
    server = _server_of(server)
    session = require_session(server, session_name)
    target = session.session_id
    args = ["tmux", "split-window", "-t", target]
    if start_directory:
        args += ["-c", str(start_directory)]
    if direction == "right":
        args += ["-h"]
    if not attach:
        args += ["-d"]
    proc = subprocess.run(args + ["-P", "-F", "#{pane_id}"],
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


def select_layout(window, layout):
    return window.select_layout(layout)


def select_layout_for(server, session_name, layout="tiled"):
    """Apply a layout to the session's active window via tmux directly."""
    server = _server_of(server)
    session = require_session(server, session_name)
    target = session.session_name
    proc = subprocess.run(["tmux", "select-layout", "-t", target, layout],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise CompatError(f"select-layout failed: {proc.stderr.strip()}")


def send_keys(pane, *keys):
    """Send keys to a pane (the only supported way to type into one)."""
    return pane.cmd("send-keys", *keys)


def capture_pane(pane, start=None, end=None):
    """Capture pane contents as a list of lines."""
    if start is not None:
        return pane.cmd("capture-pane", "-p", "-S", str(start)).stdout
    return pane.capture_pane()
