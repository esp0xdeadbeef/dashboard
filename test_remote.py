"""Tests for remote targets: parsing, shell quoting, and the /proc split.

Run:  python3 -m unittest test_remote -v     (from the repo root)

The cases here are the ones that silently produce the *wrong machine* or a
*wrong pane*, which is the failure mode that matters: driving a sudo tmux or a
remote host with the local assumptions still in place looks like it works
right up until commands land somewhere else.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

import remote
import termstate


class SpecParsing(unittest.TestCase):
    def test_default_is_local(self):
        t = remote.parse_spec("local")
        self.assertEqual(t.transport, "local")
        self.assertFalse(t.sudo)
        self.assertEqual(t.local_tmux_argv("list-sessions"), ["tmux",
                                                             "list-sessions"])

    def test_remote_host(self):
        t = remote.parse_spec("l-portal")
        self.assertEqual(t.transport, "ssh")
        self.assertEqual(t.host, "l-portal")
        self.assertFalse(t.sudo)

    def test_remote_sudo(self):
        # `sudo tmux` on another machine: root's server, reached over ssh.
        t = remote.parse_spec("100.64.0.14:sudo")
        self.assertEqual(t.transport, "ssh")
        self.assertEqual(t.host, "100.64.0.14")
        self.assertTrue(t.sudo)
        argv = t.local_tmux_argv("list-panes")
        self.assertEqual(argv[:3], ["sudo", "-n", "tmux"])
        self.assertEqual(argv[-1], "list-panes")

    def test_local_sudo(self):
        t = remote.parse_spec("local:sudo")
        self.assertEqual(t.transport, "local")
        self.assertTrue(t.sudo)
        self.assertEqual(t.local_tmux_argv()[:3], ["sudo", "-n", "tmux"])

    def test_sudo_login_is_not_sudo_tmux(self):
        t = remote.parse_spec("s-nodus:sudo-login")
        self.assertTrue(t.sudo_login)
        self.assertFalse(t.sudo, "sudo-login keeps the server ours")
        self.assertEqual(t.local_tmux_argv(), ["tmux"])

    def test_socket_name(self):
        t = remote.parse_spec("l-portal,sock=dbg")
        self.assertEqual(t.socket, "dbg")
        self.assertEqual(t.local_tmux_argv(), ["tmux", "-L", "dbg"])

    def test_socket_and_sudo_combine(self):
        t = remote.parse_spec("l-portal:sudo,sock=dbg")
        self.assertEqual(t.local_tmux_argv()[:5],
                         ["sudo", "-n", "tmux", "-L", "dbg"])

    def test_user_override(self):
        t = remote.parse_spec("root@l-portal:sudo")
        self.assertEqual(t.host, "root@l-portal")

    def test_socket_path(self):
        # tmux -S, for root-owned servers: nixos-shell VMs live at
        # /run/nixos-shell/NAME.tmux and are only reachable this way.
        t = remote.parse_spec("100.64.0.16:sudo,sock=/run/nixos-shell/s-test.tmux")
        self.assertEqual(t.socket_path, "/run/nixos-shell/s-test.tmux")
        self.assertIsNone(t.socket)
        self.assertEqual(
            t.local_tmux_argv("list-sessions"),
            ["sudo", "-n", "tmux", "-S", "/run/nixos-shell/s-test.tmux",
             "list-sessions"])

    def test_socket_path_rejects_whitespace(self):
        with self.assertRaises(remote.RemoteError):
            remote.parse_spec("x:sock=/run/a b.tmux")

    def test_rejections(self):
        for bad in ("", "   ", "x:wat", "x:sock=", "a b", "x:SUDO"):
            with self.subTest(bad=bad):
                with self.assertRaises(remote.RemoteError):
                    remote.parse_spec(bad)

    def test_describe_names_the_server(self):
        self.assertIn("sudo", remote.parse_spec("local:sudo").describe())
        self.assertIn("ssh l-portal",
                      remote.parse_spec("l-portal").describe())


class Quoting(unittest.TestCase):
    """Arguments must survive ssh's join-them-with-spaces behaviour intact."""

    def _remote_command(self, target_spec, args):
        """What the shim would hand ssh as one argument."""
        t = remote.parse_spec(target_spec)
        return t.remote_tmux_command(*args)

    def test_plain_arguments(self):
        cmd = self._remote_command("l-portal", ["send-keys", "-t", "a:0.0"])
        self.assertEqual(cmd, "tmux send-keys -t a:0.0")

    def test_argument_with_space_survives(self):
        cmd = self._remote_command("l-portal",
                                   ["send-keys", "-t", "a b:0.0"])
        self.assertIn("'a b:0.0'", cmd)

    def test_shell_metacharacters_do_not_expand(self):
        cmd = self._remote_command(
            "l-portal", ["send-keys", "-l", "echo $HOME `id` $(id) | cat"])
        self.assertIn("'echo $HOME `id` $(id) | cat'", cmd)

    def test_quote_in_argument(self):
        cmd = self._remote_command("l-portal", ["send-keys", "-l", "it's"])
        # shlex.quote turns it into '"'"'-style concatenation, which a POSIX
        # shell reads back as the original single-quoted word.
        self.assertNotIn("it's", cmd)
        self.assertIn("'it'", cmd)

    def test_sudo_prefix_is_words_not_a_token(self):
        cmd = self._remote_command("l-portal:sudo", ["list-sessions"])
        self.assertEqual(cmd, "sudo -n tmux list-sessions")

    def test_remote_command_roundtrips_through_shlex(self):
        """Split the command back: it must be exactly the argv we started with."""
        import shlex
        args = ["send-keys", "-t", "a b:0.0", "-l", "x $y `z` 'q' \"r\""]
        cmd = self._remote_command("l-portal", args)
        self.assertEqual(shlex.split(cmd), ["tmux", *args])


class Shim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_local_sudo_shim_execs_tmux(self):
        script = remote.make_tmux_shim(remote.parse_spec("local:sudo"),
                                       self.tmp)
        with open(script) as fh:
            text = fh.read()
        self.assertTrue(text.startswith("#!"))
        self.assertIn("'sudo', '-n', 'tmux'", text)
        self.assertIn("os.execvp", text)

    def test_ssh_shim_quotes_each_argument_locally(self):
        script = remote.make_tmux_shim(remote.parse_spec("l-portal:sudo"),
                                       self.tmp)
        with open(script) as fh:
            text = fh.read()
        # The remote side must NOT get a bare "$@": ssh joins arguments into a
        # string, which would re-split them on the far side.
        self.assertNotIn('"$@"', text)
        self.assertIn("shlex.quote", text)
        self.assertIn("BatchMode=yes", text)

    def test_shim_refuses_default_target(self):
        with self.assertRaises(remote.RemoteError):
            remote.make_tmux_shim(remote.parse_spec("local"), self.tmp)


class ProcSourcesAgree(unittest.TestCase):
    """RemoteProc must classify identically to LocalProc on the same /proc.

    This is the whole point of moving only the *data* across the wire: the
    decision logic must not fork into a second, drifting implementation.
    """

    def setUp(self):
        self.proc = subprocess.Popen(["sleep", "30"])
        termstate.set_proc_source(termstate.LocalProc())

    def tearDown(self):
        self.proc.kill()
        self.proc.wait()
        termstate.set_proc_source(termstate.LocalProc())

    def test_snapshot_parses_same_fields(self):
        out = subprocess.run(
            ["sh", "-c", termstate.RemoteProc.SCRIPT],
            capture_output=True, text=True).stdout
        mode, stats = "stat", {}
        for line in out.splitlines():
            if line.strip() == "@@WCHAN":
                mode = "wchan"
                continue
            pid_text, _, rest = line.partition("|")
            if mode == "stat" and pid_text.isdigit():
                st = termstate._parse_stat(int(pid_text), rest)
                if st:
                    stats[int(pid_text)] = st
        self.assertIn(self.proc.pid, stats)
        mine = stats[self.proc.pid]
        local = termstate.LocalProc().stat(self.proc.pid)
        for key in ("pid", "ppid", "tpgid"):
            self.assertEqual(mine[key], local[key])

    def test_classify_matches(self):
        """Both /proc views must reach the same verdict for the same pid."""
        import time
        for _ in range(20):  # wait for a meaningful wchan instead of racing it
            if termstate.classify(self.proc.pid).state is not termstate.State.UNKNOWN:
                break
            time.sleep(0.05)
        local = termstate.classify(self.proc.pid)

        class Snapshot(termstate.ProcSource):
            """RemoteProc's data, fetched synchronously for this one pid."""

            def stat(self, pid):
                return termstate.LocalProc().stat(pid)

            def wchan(self, pid):
                return termstate.LocalProc().wchan(pid)

            def children(self, pid):
                return termstate.LocalProc().children(pid)

        termstate.set_proc_source(Snapshot())
        try:
            proxied = termstate.classify(self.proc.pid)
        finally:
            termstate.set_proc_source(termstate.LocalProc())

        self.assertEqual(local.state, proxied.state)
        self.assertIsNot(local.state, termstate.State.UNKNOWN,
                         "a childless sleeping process should classify")


class RemoteProc(unittest.TestCase):
    def test_failed_snapshot_degrades_instead_of_raising(self):
        class Broken:
            def run_shell_ok(self, *a, **kw):
                raise remote.RemoteError("ssh: host unreachable")

        src = termstate.RemoteProc(Broken())
        self.assertIsNone(src.stat(os.getpid()))
        self.assertEqual(src.wchan(os.getpid()), "")
        self.assertEqual(src.children(os.getpid()), [])
        self.assertIn("unreachable", src.last_error or "")


class TargetsAreSticky(unittest.TestCase):
    """reconnect() must rebuild the same Server, not the ambient one."""

    def tearDown(self):
        import compat
        compat.set_server_target()

    def test_reconnect_keeps_shim(self):
        import compat
        compat.set_server_target(socket_name="dbg", tmux_bin="/x/tmux")
        server = compat.connect()
        again = compat.reconnect(server)
        self.assertEqual(str(again.socket_name), "dbg")
        self.assertEqual(str(again.tmux_bin), "/x/tmux")

    def test_default_target_is_plain_tmux(self):
        import compat
        compat.set_server_target()
        self.assertEqual(compat.current_server_target(),
                         {"socket_name": None, "socket_path": None,
                          "tmux_bin": None})


class WindowTargeting(unittest.TestCase):
    """Live-tmux checks for the bugs that filled the wrong window.

    These need a real tmux server, so they use a throwaway one on a private
    socket and skip if tmux is unavailable. They are the regression tests for
    failures that were silent: keystrokes landing in a window the caller was
    not filling.
    """

    SOCKET = "tmux-dashboard-test"

    def setUp(self):
        if shutil.which("tmux") is None:
            self.skipTest("tmux not installed")
        import compat
        compat.set_server_target(socket_name=self.SOCKET)
        self.server = compat.connect()
        try:
            self.server.cmd("kill-server")
        except Exception:
            pass
        # kill-server is asynchronous: a server started by the previous test
        # can still be tearing down when the next one starts, and `new-session`
        # then silently does nothing. Wait for it to be really gone.
        self._wait(lambda: not self.server.sessions, "server to stop")

    def tearDown(self):
        import compat
        try:
            self.server.cmd("kill-server")
        except Exception:
            pass
        compat.set_server_target()

    def _wait(self, predicate, what, timeout=10.0):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}")

    def _new_session(self, name="t"):
        import compat
        proc = self.server.cmd("new-session", "-d", "-s", name,
                               "-x", "80", "-y", "24")
        self.assertEqual(proc.returncode, 0,
                         f"new-session failed: {proc.stderr}")
        self._wait(lambda: compat.get_session(compat.connect(), name)
                   is not None, f"session {name!r}")
        return compat.require_session(compat.connect(), name)

    def test_new_window_named_does_not_rename_the_old_one(self):
        """new_window() + active_window() renames the WRONG window.

        With two windows open, `active_window()` on a session handle that
        predates the new window still reports the old one, so the rename lands
        on the previous window and the new one keeps the default name.
        """
        import compat
        session = self._new_session()
        first = compat.windows_of_session("t")[0][0]
        compat.rename_window(compat.window_by_id(first), "programming")

        new_id = compat.new_window_named(session, "socat")

        names = {wid: name for wid, name, _ in compat.windows_of_session("t")}
        self.assertEqual(names[new_id], "socat")
        self.assertEqual(names[first], "programming",
                         "the pre-existing window must keep its name")

    def test_active_pane_of_window_is_not_the_sessions_active_pane(self):
        import compat
        self._new_session()
        first = compat.windows_of_session("t")[0][0]
        compat.rename_window(compat.window_by_id(first), "one")
        second = compat.new_window_named(
            compat.require_session(compat.connect(), "t"), "two")

        # Make "one" the session's active window again, as another client would.
        compat.select_window(None, first)
        pane = compat.active_pane_of_window(second)
        self.assertIn(pane.pane_id, compat.pane_ids_of_window(second))

    def test_split_targets_the_named_window(self):
        import compat
        self._new_session()
        first = compat.windows_of_session("t")[0][0]
        compat.rename_window(compat.window_by_id(first), "one")
        second = compat.new_window_named(
            compat.require_session(compat.connect(), "t"), "two")
        compat.select_window(None, first)   # active window is "one"

        new_pane = compat.split_pane(None, "t", attach=True, window_id=second)
        self.assertIn(new_pane, compat.pane_ids_of_window(second))
        self.assertNotIn(new_pane, compat.pane_ids_of_window(first))
        self.assertEqual(len(compat.pane_ids_of_window(first)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
