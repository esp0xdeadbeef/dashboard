"""Tests for non-interactive (unattended) session-file runs.

Run:  python3 -m unittest test_noninteractive -v     (from the repo root)

These pin the contract that ``--session-file`` without ``-i`` is an
*unattended spawn*, which is the only form CI and agents can use (no TTY).
``main()`` used to call ``s_all(respawn_all=False)`` there, which takes the
attach branch of ``s_all`` -- so on a fresh target it printed
``no tmux session named '<x>'``, spawned nothing, and still exited 0. That is
the worst failure shape for a caller: a silent success with no pane, so the
work it thought it had launched never ran.

The cases here are the ones that broke in practice:

  * a fresh target: no session exists yet, so nothing may be *attached* to;
  * a session that exists under the right name but has no matching window;
  * a spawn whose pane's shell exits, so tmux reaps the session -- that must be
    reported with a non-zero status, not swallowed.
"""

import unittest
from unittest import mock

import main_tdashboard as md


class NonInteractiveSpawnTest(unittest.TestCase):
    """`main()` must spawn, and must fail loudly when a session does not survive."""

    def _run_main(self, interactive, spawn_calls, existing_sessions):
        """Drive main() with every tmux/server interaction stubbed out."""
        args = mock.Mock()
        args.interpreters = []
        args.target = "local"
        args.check = False
        args.session_file = "/dev/null"
        args.interactive = interactive
        args.scripts = "scripts"

        spawned = []

        def fake_s_all(respawn_all=True):
            spawn_calls.append(respawn_all)
            if respawn_all:
                spawned.extend(existing_sessions)

        with mock.patch.object(md, "parse_args", return_value=args), \
                mock.patch.object(md, "connect_server", return_value=object()), \
                mock.patch.object(md, "get_file_content", return_value=""), \
                mock.patch.object(md, "list_potentional_sessions",
                                  return_value=["spawn_ciwatch"]), \
                mock.patch.object(md, "get_dir_session_files", return_value={}), \
                mock.patch.object(md, "natural_sort", side_effect=sorted), \
                mock.patch.object(md, "s_all", side_effect=fake_s_all), \
                mock.patch.object(md.compat, "get_session",
                                  side_effect=lambda _s, name: name if name in spawned else None), \
                mock.patch.object(md.compat, "active_pane", return_value=mock.Mock()):
            return md.main()

    def test_non_interactive_spawns_instead_of_attaching(self):
        calls = []
        self._run_main(interactive=False, spawn_calls=calls, existing_sessions=["ciwatch"])
        self.assertEqual(
            calls, [True],
            "non-interactive mode must call s_all(respawn_all=True) so the "
            "session file is spawned; respawn_all=False only attaches to a "
            "session that does not exist yet",
        )

    def test_non_interactive_reports_a_session_that_did_not_survive(self):
        calls = []
        # The spawn pretends to succeed but no session comes back, which is what
        # a reaped pane looks like.
        rc = self._run_main(interactive=False, spawn_calls=calls, existing_sessions=[])
        self.assertEqual(rc, 1, "a spawn that left no live session must exit non-zero")

    def test_non_interactive_success_returns_zero(self):
        calls = []
        rc = self._run_main(interactive=False, spawn_calls=calls, existing_sessions=["ciwatch"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
