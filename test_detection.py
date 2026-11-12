"""Tests for the prompt/progress detection.

Run:  python3 -m unittest test_detection -v     (from the repo root)

The cases here are all ones that broke in practice:

  * a console that writes async noise AFTER a prompt (kernel printk, a
    supervisor, journald) -- matching "the last line" then finds the noise and
    declares the pane busy though it is at a prompt;
  * a console that writes noise OVER a prompt -- the prompt and the noise are
    one line, so dropping noise-only lines deletes the prompt;
  * a terminal host (`qemu-system-x86_64`) -- the process is blocked on the tty
    for its whole life, so process state alone claims READY during a boot, at a
    login prompt, and while a command runs;
  * a prompt belonging to the shell that launched the guest, not the guest;
  * an old prompt above a still-running command.
"""

import unittest
from unittest import mock
import base64
import re
import hashlib

import main_tdashboard
import prompts
import termstate


class PromptTable(unittest.TestCase):
    def test_clean_prompt(self):
        m = prompts.match_screen("[root@isp-neon:~/src]#")
        self.assertIsNotNone(m)
        self.assertEqual(m.tool, "root-shell")

    def test_noise_after_prompt(self):
        screen = "\n".join([
            "[root@isp-neon:~/src]#",
            "[   33.5] zib-thing[1699]: sudo: /run/bindfs: command not found",
            "[   34.1] lxc-start: lxc-osee: no access to /var/lib/lxc",
        ])
        m = prompts.match_screen(screen)
        self.assertIsNotNone(m, "noise after a prompt must not hide it")
        self.assertEqual(m.tool, "root-shell")

    def test_noise_written_over_prompt(self):
        # The console wrote a log line onto the same physical line as the
        # prompt. Dropping the line would lose the prompt entirely.
        screen = ("[root@isp-neon:~/src]# [   33.548176] "
                  "zib-start-svc[1699]: sudo: bindfs: command not found")
        m = prompts.match_screen(screen)
        self.assertIsNotNone(m, "noise overwriting a prompt must not hide it")
        self.assertEqual(m.tool, "root-shell")

    def test_booting_is_not_a_prompt(self):
        screen = "[  OK  ] Started Foo.\n[   12.3] bar: baz starting"
        self.assertIsNone(prompts.match_screen(screen))

    def test_login_prompt_is_not_a_shell(self):
        self.assertIsNone(prompts.match_screen("isp-neon login: root"))

    def test_after_marker_ignores_earlier_prompt(self):
        screen = "[root@h:/]# echo M\nM\n"
        # Only an old prompt on screen: after the command there is no prompt.
        self.assertIsNone(prompts.match_screen(screen, after="\nM\n"))

    def test_after_marker_uses_last_occurrence(self):
        # The terminal echoes the marker, so it appears twice; the last one is
        # the real end of output.
        screen = "[root@h:/]# echo M\nM\n[root@h:/]#"
        m = prompts.match_screen(screen, after="M")
        self.assertIsNotNone(m)
        self.assertEqual(m.tool, "root-shell")


class HypervisorPrompts(unittest.TestCase):
    """QEMU's monitor and GRUB are interactive prompts of their own."""

    def test_qemu_monitor_prompt(self):
        m = prompts.match_screen("QEMU 10.2.4 monitor - type 'help'\n(qemu) ")
        self.assertIsNotNone(m)
        self.assertEqual(m.tool, "qemu-monitor")

    def test_qemu_monitor_survives_noise(self):
        screen = "(qemu) [   12.3] something: yammering"
        m = prompts.match_screen(screen)
        self.assertIsNotNone(m, "noise after the monitor prompt hides it")
        self.assertEqual(m.tool, "qemu-monitor")

    def test_monitor_is_a_nested_shell(self):
        # A REPL/monitor accepts input but rejects shell commands, so a caller
        # that wants a shell must not send into it.
        m = prompts.match_line("(qemu)")
        self.assertTrue(m.safe_to_send, "the monitor is safe for a caller that means it")
        self.assertTrue(m.is_nested_shell(), "but it is not a shell")

    def test_shell_is_not_nested(self):
        m = prompts.match_line("[root@h:/]#")
        self.assertFalse(m.is_nested_shell())

    def test_grub_prompt(self):
        m = prompts.match_screen("grub> ")
        self.assertIsNotNone(m)
        self.assertEqual(m.tool, "grub-shell")

    def test_guest_shell_not_confused_with_monitor(self):
        m = prompts.match_screen("[root@isp-cobalt:~/x]#")
        self.assertEqual(m.tool, "root-shell")


class StablePromptProbe(unittest.TestCase):
    """The `probe=True` check in at_end, tested without a live pane.

    It exists because a pane hosting a terminal (QEMU serial console, screen,
    minicom) has its foreground process blocked on the tty for its whole life,
    so /proc says "ready" during a boot, at a login prompt, and while a command
    runs. The only signal left is: send Enter, see if the prompt line settles.
    """

    def _signature(self, lines):
        out = []
        for line in lines:
            if main_tdashboard._CONSOLE_JUNK.search(line):
                continue
            out.append(line.rstrip())
        while out and not out[-1].strip():
            out.pop()
        return "\n".join(out)

    def test_junk_is_ignored_when_comparing(self):
        # Async console junk must not make two samples of the same pane differ:
        # the guest prompt is identical, only the timestamped line changes.
        # The rule is structural (a timestamp prefix), so it holds for any
        # daemon, not just the one that happened to be noisy on one machine.
        a = self._signature([
            "[root@h:/]#",
            "[   12.3] some-daemon[1]: a message",
        ])
        b = self._signature([
            "[root@h:/]#",
            "[   99.9] another-daemon: a different message",
        ])
        self.assertEqual(a, b)
        self.assertEqual(a, "[root@h:/]#")

    def test_unstamped_text_is_not_junk(self):
        # Only timestamped output is noise. Plain text must survive, or a
        # prompt made of ordinary words would be discarded too.
        self.assertEqual(
            self._signature(["Container 'client' started."]),
            "Container 'client' started.",
        )

    def test_prompt_line_is_the_last_text_line(self):
        sig = self._signature(["[  OK  ] Started Foo.", "[root@h:/]#", "", ""])
        self.assertEqual(sig.splitlines()[-1], "[root@h:/]#")

    def test_boot_output_does_not_look_like_a_prompt(self):
        sig = self._signature(["[  OK  ] Started Container 'client'."])
        self.assertIsNone(prompts.match_line(sig.splitlines()[-1]))


class BuildProgressIsNotAShell(unittest.TestCase):
    """A build in progress must never be reported as a prompt.

    Measured 2026-11-11 on isp-cobalt: `nixos-shell` was still building when
    the acceptance probe ran, and `wait_guest` returned True in the middle of
    the build. The probe sends a bare Enter, so there is no echo to
    distinguish "prompt" from "a program printing":

        [17/21 built, 3 copied (13.7 MiB), 2.6 MiB DL]

    is perfectly stable under an empty Enter, was unknown to the prompt table,
    and so was accepted -- the probe then typed into the build, and every hop
    reported `<no output>` because the commands ran on the host shell (or on
    nothing) instead of the guest.

    The fix is not "more stable": the shapes that mean "still working" are
    rejected outright, leaving the redraw test to decide the rest.
    """

    WORKING = [
        "[17/21 built, 3 copied (13.7 MiB), 2.6 MiB DL]",
        "[1/11/21 built, 3 copied (13.7 MiB), 2.6 MiB DL] building unit-dbus-ber",
        "building '/nix/store/abc-system-units.drv'...",
        "copying path '/nix/store/x' from 'https://cache.nixos.org'...",
        "unpacking sources",
        "fetching path '/nix/store/y'...",
    ]

    def test_working_lines_are_rejected(self):
        for line in self.WORKING:
            self.assertTrue(
                any(p.search(line) for p in main_tdashboard._NOT_A_SHELL_LINE),
                f"{line!r} would be accepted as a prompt")

    def test_real_prompts_still_pass(self):
        for line in ("[root@isp-cobalt:~]#", "user@host:~$",
                     "[nix-shell:~/repo]$"):
            self.assertFalse(
                any(p.search(line) for p in main_tdashboard._NOT_A_SHELL_LINE),
                f"{line!r} must still count as a prompt")

    def test_table_does_not_already_cover_it(self):
        # Guards the reason this class exists: the prompt table cannot help,
        # because a build line is not a *prompt* and must not become one.
        for line in self.WORKING:
            self.assertIsNone(prompts.match_line(line))


class LoginBannerIsNotAShell(unittest.TestCase):
    """A stable login banner must never be treated as a shell prompt.

    `_stable_prompt` compares the last line to itself, and a login banner is
    perfectly stable, so it passed and a caller then typed commands into a login
    prompt. Measured 2026-11-10 on isp-neon:

        isp-neon login: root (automatic login)      <- reported READY
    """

    def test_login_banner_matches_the_guard(self):
        banner = "isp-neon login: root (automatic login)"
        self.assertIsNotNone(main_tdashboard._LOGIN_PROMPT.search(banner))

    def test_plain_login_prompt_matches(self):
        self.assertIsNotNone(
            main_tdashboard._LOGIN_PROMPT.search("isp-neon login:"))

    def test_shell_prompt_does_not_match(self):
        for line in ("[root@isp-neon:~]#", "root@host:~$"):
            self.assertIsNone(main_tdashboard._LOGIN_PROMPT.search(line))


class WaitForMessage(unittest.TestCase):
    """wait_untill_msg must not match the echo of the command it waits on.

    The terminal echoes every typed line, so a plain substring search over the
    screen matches the command that was just sent. That makes the wait a no-op
    and reports success before the program has produced anything -- observed as
    "ppp0 is UP" while the interface did not exist, because the marker was
    inside the `if ...; then echo <marker>_UP` that had just been typed.
    """

    def test_echoed_command_is_not_output(self):
        echoed = ["[root@h:~]# if ip show ppp0; then echo M_UP; else echo M_NO; fi"]
        self.assertFalse(main_tdashboard._message_in_output(echoed, "M_UP"))

    def test_real_output_matches(self):
        lines = [
            "[root@h:~]# if ip show ppp0; then echo M_UP; else echo M_NO; fi",
            "M_UP",
        ]
        self.assertTrue(main_tdashboard._message_in_output(lines, "M_UP"))

    def test_absent_message_does_not_match(self):
        lines = ["[root@h:~]# echo M_UP", "M_NO"]
        self.assertFalse(main_tdashboard._message_in_output(lines, "M_UP"))

    def test_message_without_prompt_echo_matches(self):
        # A program printing the marker with no prompt prefix is real output.
        self.assertTrue(main_tdashboard._message_in_output(["M_UP"], "M_UP"))


class TerminalHost(unittest.TestCase):
    """A pane whose foreground program hosts another terminal."""

    def test_user_at_host_prompt_is_a_shell(self):
        """`user@host <cwd> >` must match: it is what stock bash/zsh emit.

        Every generic catch in prompts.txt used `^[^\\s]*` as the whole
        prefix, so a prompt with a space before the sigil matched nothing:

          $ prompts.match_line('root@isp-cobalt:~/ >')
          None

        Measured 2026-11-11 on the cobalt HAT: `pane_state` then answered
        "hosts a terminal; no prompt on screen" for a guest sitting at exactly
        that prompt, while `_stable_prompt` could see it was stable. The
        disagreement made `is_at_guest_shell` false and every HAT verb refused
        to type into a healthy VM.
        """
        for line in (
            "root@isp-cobalt:~/ >",
            "root@isp-cobalt:/ #",
            "user@host:~$",
            "user@host /var/log %",
        ):
            m = prompts.match_line(line)
            self.assertIsNotNone(m, f"{line!r} must be recognised as a prompt")
            self.assertEqual(m.kind, "shell", f"{line!r} must be a shell prompt")

    def test_bracketed_and_nested_prompts_keep_their_match(self):
        """The new pattern must not shadow the more specific ones."""
        self.assertEqual(prompts.match_line("[root@host ~]#").tool, "user-shell")
        self.assertEqual(prompts.match_line("msf6 >").tool, "metasploit")
        self.assertEqual(prompts.match_line("(qemu)").tool, "qemu-monitor")

    def test_qemu_is_a_terminal_host(self):
        self.assertTrue(termstate._is_terminal_host("qemu-system-x8"))
        self.assertFalse(termstate._is_terminal_host("bash"))

    def test_terminal_host_comes_from_the_chain_not_tmux(self):
        """`is_terminal_host` must read `/proc`, not `pane_current_command`.

        Measured 2026-11-11 on the HAT cobalt fixture: the pane's chain was
        `zsh > .nixos-shell-wr > .qemu-system-x8` while tmux reported
        `pane_current_command=bash`. The old body trusted tmux, answered False,
        skipped the redraw probe, and `at_end` reported "not at the guest
        shell" for a guest sitting at its prompt -- so the acceptance probe
        typed into the wrong place and reported FAIL.

        The fake `pane_info` reproduces exactly that disagreement.
        """
        chain = {2415971: "zsh", 2416227: ".nixos-shell-wr", 2441104: ".qemu-system-x8"}
        fake_state = termstate.PaneState(
            state=termstate.State.READY,
            reason="fake",
            pid=2441104,
            comm=chain[2441104],
            chain=(2415971, 2416227, 2441104),
        )
        with mock.patch.object(termstate, "pane_state", return_value=fake_state), \
             mock.patch.object(termstate, "_comm_of", side_effect=chain.get), \
             mock.patch.object(
                 termstate, "pane_info",
                 return_value=termstate.PaneInfo(
                     target="%1", pid=2415971, tty="/dev/pts/0",
                     command="bash", width=80, height=24,
                 ),
             ):
            self.assertTrue(
                termstate.is_terminal_host("%1"),
                "a QEMU pane must be a terminal host even when tmux reports the "
                "pane's original shell as pane_current_command",
            )

    def test_plain_shell_pane_is_not_a_terminal_host(self):
        fake_state = termstate.PaneState(
            state=termstate.State.READY, reason="fake", pid=10, comm="bash",
            chain=(10,),
        )
        with mock.patch.object(termstate, "pane_state", return_value=fake_state), \
             mock.patch.object(termstate, "_comm_of", side_effect={10: "bash"}.get):
            self.assertFalse(termstate.is_terminal_host("%1"))

    # These exercise the rule directly rather than a live pane: a live pane's
    # contents (and which prompt it happens to show) change between runs.

    def _resolve(self, prompt_line, expect_host):
        """Apply pane_state's expect_host rule to a hypothetical prompt."""
        m = prompts.match_line(prompt_line)
        return m, (m is not None and expect_host in m.line)

    def test_expect_host_rejects_foreign_prompt(self):
        m, ok = self._resolve("[root@isp-neon:~/x]#", expect_host="isp-cobalt")
        self.assertIsNotNone(m)
        self.assertFalse(ok, "a prompt from the wrong host is not readiness")

    def test_expect_host_accepts_own_prompt(self):
        m, ok = self._resolve("[root@isp-neon:~/x]#", expect_host="isp-neon")
        self.assertIsNotNone(m)
        self.assertTrue(ok)

    def test_monitor_prompt_is_not_the_guest_shell(self):
        # The QEMU monitor is a prompt, but not the guest's: expect_host must
        # not accept it as "the guest is ready for a shell command".
        m, ok = self._resolve("(qemu)", expect_host="isp-neon")
        self.assertIsNotNone(m)
        self.assertFalse(ok)


class PagerIsNotAShell(unittest.TestCase):
    """A pager (`less`/`more`/`most`) owning the tty is a prompt, not a shell.

    `git log`, `man`, a long `--help` all leave a pager blocked reading the tty
    -- which process state correctly reads as "wants input", but a shell
    command typed there is treated by `less` as a search or a motion and never
    runs. Worse, the screen shows the top of the page with no `--More--` yet,
    so the screen table's `pager` entry does not match either. The pane therefore
    looked READY and the caller's command vanished into the pager.

    Detection is on the owner's process name, so it does not depend on what the
    page happens to be showing.
    """

    def _fake_procs(self, pager_comm):
        # shell 100 (bash) + foreground pager 200 in its own process group.
        table = {
            100: dict(pid=100, comm="bash", state="S", ppid=1, tpgid=200,
                      utime=0, stime=0),
            200: dict(pid=200, comm=pager_comm, state="S", ppid=100, tpgid=200,
                      utime=0, stime=0),
        }
        kids = {100: [200], 200: []}

        class FakeProc(termstate.ProcSource):
            def stat(self, pid):
                return table.get(pid)

            def wchan(self, pid):
                # Both bash and the pager are blocked reading the tty -- which
                # is exactly why process state alone cannot tell them apart.
                return "n_tty_read" if pid in table else ""

            def children(self, pid):
                return list(kids.get(pid, []))

        return FakeProc()

    def _pane_state(self, pager_comm, screen):
        class StaticSource(termstate.TmuxSource):
            def run(self, *args):
                return 0, screen, ""

        real_proc = termstate.proc_source()
        real_tmux = termstate.tmux_source()
        real_info = termstate.pane_info
        termstate.set_proc_source(self._fake_procs(pager_comm))
        termstate.set_tmux_source(StaticSource())
        termstate.pane_info = lambda t: termstate.PaneInfo(
            target=t, pid=100, tty="/dev/pts/0", command="bash",
            width=80, height=24)
        self.addCleanup(termstate.set_proc_source, real_proc)
        self.addCleanup(termstate.set_tmux_source, real_tmux)
        self.addCleanup(setattr, termstate, "pane_info", real_info)
        return termstate.pane_state("%0")

    def test_less_is_busy_not_ready(self):
        st = self._pane_state("less", "commit 1a2b3c4\n    the first commit\n:")
        self.assertIs(st.state, termstate.State.BUSY,
                      "a pane inside `less` must not be READY")
        self.assertIsNotNone(st.prompt)
        self.assertEqual(st.prompt.tool, "pager")
        self.assertFalse(st.safe_to_send,
                         "a command line must not be sent into a pager")

    def test_less_at_top_of_page_is_still_detected(self):
        # No `--More--` or `:` on screen yet -- the screen table would miss it.
        st = self._pane_state("less", "commit 1a2b3c4\n    the first commit")
        self.assertIs(st.state, termstate.State.BUSY)
        self.assertEqual(st.tool, "pager")

    def test_more_and_most_are_pagers(self):
        for comm in ("more", "most", "moar"):
            st = self._pane_state(comm, "some text")
            self.assertIs(st.state, termstate.State.BUSY, comm)

    def test_at_end_refuses_a_pager(self):
        class StaticSource(termstate.TmuxSource):
            def run(self, *args):
                return 0, "commit 1a2b3c4\n    the first commit", ""

        real_proc = termstate.proc_source()
        real_tmux = termstate.tmux_source()
        real_info = termstate.pane_info
        termstate.set_proc_source(self._fake_procs("less"))
        termstate.set_tmux_source(StaticSource())
        termstate.pane_info = lambda t: termstate.PaneInfo(
            target=t, pid=100, tty="/dev/pts/0", command="bash",
            width=80, height=24)
        self.addCleanup(termstate.set_proc_source, real_proc)
        self.addCleanup(termstate.set_tmux_source, real_tmux)
        self.addCleanup(setattr, termstate, "pane_info", real_info)

        class Pane:
            pane_id = "%0"

        self.assertFalse(main_tdashboard.at_end(Pane()),
                         "at_end must not report a pager as idle")


class LearnedPrompts(unittest.TestCase):
    """A prompt must not need to be written down to be recognised.

    The curated table (prompts.txt) is a guess about what prompts look like and
    will always be missing the next one: a themed shell's "└─[#]", a host's
    PS1, a vendor CLI. These tests pin the *learning* path that replaces
    guessing, including the case that made it necessary -- a pane hosting
    another terminal, where process state can only ever say "blocked on tty".
    """

    def setUp(self):
        prompts.forget_learned()

    def tearDown(self):
        prompts.forget_learned()

    def test_unknown_prompt_is_learned_not_guessed(self):
        self.assertIsNone(prompts.match_line("└─[#]"),
                          "the table must not know this prompt")
        prompts.learn("└─[#]")            # seen once: still a candidate
        prompts.learn("└─[#]")            # seen again: promoted
        m = prompts.match_line("└─[#]")
        self.assertIsNotNone(m)
        self.assertEqual(m.kind, "shell")

    def test_one_sighting_is_not_evidence(self):
        # A command's output line is also the last line under a ready shell.
        # Learning it on first sight would memorise an error message as a
        # prompt forever.
        prompts.learn("error: could not open foo.conf")
        self.assertIsNone(prompts.match_line("error: could not open foo.conf"))
        prompts.learn("error: could not open foo.conf")
        self.assertIsNotNone(prompts.match_line("error: could not open foo.conf"))

    def test_stable_evidence_promotes_immediately(self):
        # The redraw probe already proved it survives an empty Enter.
        prompts.learn("└─[#]", threshold=1)
        self.assertIsNotNone(prompts.match_line("└─[#]"))

    def test_generalises_volatile_parts(self):
        prompts.learn("└─[root@s-test] - [19:04:22] - [/var/log]", threshold=1)
        m = prompts.match_line("└─[root@s-test] - [20:11:59] - [/var/log]")
        self.assertIsNotNone(m, "a redraw with a new time must still match")

    def test_learned_beats_generic_table_entry(self):
        # Once the real prompt is known, it must win over the generic
        # "ends in # or $" catch in prompts.txt.
        prompts.learn("└─[#]", tool="s-test-shell", threshold=1)
        m = prompts.match_line("└─[#]")
        self.assertEqual(m.tool, "s-test-shell")

    def test_learning_is_bounded(self):
        for i in range(prompts._LEARNED_LIMIT + 50):
            prompts.learn(f"prompt-{i}", threshold=1)
        self.assertLessEqual(len(prompts.learned()), prompts._LEARNED_LIMIT)

    def test_learn_rejects_blank_and_garbage(self):
        prompts.learn("   ", threshold=1)
        self.assertEqual(prompts.learned(), ())


class TerminalHostLearning(unittest.TestCase):
    """The pane type that forced auto-detection to exist."""

    def setUp(self):
        prompts.forget_learned()

    def tearDown(self):
        prompts.forget_learned()
        termstate.set_proc_source(termstate.LocalProc())

    def test_guest_prompt_becomes_ready_without_a_regex(self):
        """A QEMU console at "└─[#]" must be recognised after one look.

        This mirrors what pane_state does with `stable=True`: the process is
        blocked on the tty for its whole life, so the screen is the only
        signal, and the screen contained no prompt the table knew.
        """
        self.assertIsNone(prompts.match_line("└─[#]"))
        line = prompts.last_line("s-test login: root\n└─[#]")
        prompts.learn(line, threshold=1)
        m = prompts.match_screen("s-test login: root\n└─[#]")
        self.assertIsNotNone(m)
        self.assertTrue(m.safe_to_send)

    def test_boot_output_is_still_not_a_prompt(self):
        """Learning must not make a booting console look ready."""
        prompts.learn("<<< Welcome to NixOS 26.05 (x86_64) - hvc0 >>>", threshold=2)
        prompts.learn("[  OK  ] Started SSH Daemon.", threshold=2)
        self.assertIsNone(prompts.match_screen("[  OK  ] Started SSH Daemon."))


class StreamFraming(unittest.TestCase):
    """The checksummed read path used for long output over a serial console.

    Measured on l-portal, reading `ps auxwwwww` through `tio`:

      * `pane_capture` returned 14 of ~190 rows (one screenful) and said so
        nowhere;
      * a per-line `payload|md5` scheme kept 287 records, reported
        `dropped=0`, and produced 40 malformed rows. Junk splitting a record
        leaves two self-consistent halves, so validation passes on fragments.

    These tests pin the framing rules that make the difference.
    """

    REC = main_tdashboard.STREAM_RECORD

    def _record(self, seq, total, text):
        payload = base64.b64encode(text.encode()).decode()
        digest = hashlib.md5(payload.encode()).hexdigest()[:8]
        return f"{seq}:{total}:{payload}:{digest}"

    def test_pristine_record_parses(self):
        line = self._record(3, 10, "root  1  0.0 init")
        m = self.REC.match(line)
        self.assertIsNotNone(m)
        self.assertEqual((m.group(1), m.group(2)), ("3", "10"))

    def test_kernel_spam_after_record_is_not_a_record(self):
        """The console writes over the line; the record must not match."""
        line = self._record(3, 10, "x") + \
            "  [  316.4] mt7996e: Failed to del Host Multicast Database"
        self.assertIsNone(self.REC.match(line))

    def test_split_record_halves_are_detectable_as_a_gap(self):
        """The real failure mode: a split record is self-consistent.

        Both halves look like valid `payload|checksum` pairs, so a per-record
        check cannot reject them. Only the sequence numbers reveal the loss --
        which is why the framing carries seq/total.
        """
        text = "root  42  0.0  something-long-enough-to-split"
        whole = self._record(7, 9, text)
        a, b = whole[:len(whole) // 2], whole[len(whole) // 2:]
        # Neither half is a *complete* record any more.
        self.assertIsNone(self.REC.match(a))
        self.assertIsNone(self.REC.match(b))
        # And the sequence has a hole where 7 should be.
        seen = {1, 2, 3, 4, 5, 6, 8, 9}
        self.assertEqual([i for i in range(1, 10) if i not in seen], [7])

    def test_totals_must_agree(self):
        """Records from two different attempts must not be mixed."""
        self.assertEqual({10, 10, 10}, {10})
        self.assertNotEqual({10}, {10, 11})

    def test_checksum_is_over_the_base64_text(self):
        """Hash the payload as the board does, not the decoded bytes.

        Getting this wrong validated 0 of 536 records in practice.
        """
        text = "root  1  0.0 init"
        payload = base64.b64encode(text.encode()).decode()
        as_board = hashlib.md5(payload.encode()).hexdigest()[:8]
        as_decoded = hashlib.md5(text.encode()).hexdigest()[:8]
        self.assertNotEqual(as_board, as_decoded)
        line = f"1:1:{payload}:{as_board}"
        self.assertIsNotNone(self.REC.match(line))


class PaneStreamReassembly(unittest.TestCase):
    """pane_stream's reassembly, exercised offline with a fake pane.

    These do not need a network, a tmux server or a board: the transport is
    replaced by a screen built here. That matters because the interesting
    logic -- gap detection and the retry -- is exactly what a live test
    against one remote host would fail to pin down anyway.
    """

    def _board_screen(self, lines, drop=(), spam_after=()):
        """A captured screen, framed exactly as the board produces it.

        The board encodes the WHOLE stream and then wraps it at 60 columns, so
        chunks are mid-stream and only the last one carries padding. Modelling
        it per-line instead (encode each line separately) produces records
        that cannot be concatenated, which is a test bug, not a code bug --
        verified with `printf ... | base64 -w 60` on the host.

        `drop` are 1-based seq numbers to omit (a record lost to noise);
        `spam_after` are seq numbers after which a kernel line is injected.
        """
        text = "\n".join(lines) + ("\n" if lines else "")
        stream = base64.b64encode(text.encode()).decode()
        # No output at all means NO records -- not one empty record, which
        # would parse as a corrupt line and be misreported as noise.
        chunks = ([stream[i:i + 60] for i in range(0, len(stream), 60)]
                  if stream else [])
        total = len(chunks)
        out = ["__START__"]
        for i, chunk in enumerate(chunks, 1):
            if i in drop:
                continue
            # The board re-encodes the (already base64) chunk before hashing.
            reencoded = base64.b64encode(chunk.encode()).decode()
            digest = hashlib.md5(reencoded.encode()).hexdigest()[:8]
            out.append(f"{i}:{total}:{chunk}:{digest}")
            if i in spam_after:
                out.append("[  316.4] mt7996e wlp1s0: Failed to del Host "
                           "Multicast Database")
        out.append("__END__")
        return "\n".join(out)

    def _run(self, screens, lines):
        """Drive pane_stream over a sequence of canned screens."""
        calls = {"n": 0}

        state = {"marker": None}

        def fake_send(pane, keys):
            # pane_stream sends "<marker>_START; ..." -- keep the marker so the
            # fake screen can emit the very same one.
            m = re.search(r"(STREAM\d+_?\d*)_START", keys)
            if m:
                state["marker"] = m.group(1)

        def fake_wait(pane, msg, **kw):
            return True

        class FakeSource:
            def run(self, *args):
                idx = min(calls["n"], len(screens) - 1)
                calls["n"] += 1
                mk = state["marker"] or "STREAM0"
                return 0, screens[idx].replace(
                    "__START__", f"{mk}_START").replace(
                    "__END__", f"{mk}_END"), ""

        with mock.patch.object(main_tdashboard, "wait_untill_msg", fake_wait), \
             mock.patch.object(main_tdashboard.compat, "send_keys",
                               fake_send), \
             mock.patch.object(main_tdashboard.termstate, "tmux_source",
                               lambda: FakeSource()), \
             mock.patch.object(main_tdashboard, "_pane_target",
                               lambda p: "%1"):
            return main_tdashboard.pane_stream(
                object(), "ps auxwwwww", attempts=len(screens))

    def test_clean_screen_round_trips(self):
        lines = ["USER PID"] + [f"root {i} proc-{i:03d}-padding-padding"
                                for i in range(1, 8)]
        got = self._run([self._board_screen(lines)], lines)
        self.assertEqual(got.splitlines(), lines)

    def test_kernel_spam_between_records_is_ignored(self):
        """Spam lines must not be parsed as records, nor hide real ones."""
        lines = ["USER PID"] + [f"root {i} proc-{i:03d}-padding-padding"
                                for i in range(1, 8)]
        got = self._run([self._board_screen(lines, spam_after={1, 2, 3})], lines)
        self.assertEqual(got.splitlines(), lines)

    def test_missing_record_raises_instead_of_truncating(self):
        """A gap must be fatal, never a short-but-plausible answer."""
        lines = ["USER PID"] + [f"root {i} proc-{i:03d}-padding-padding"
                                for i in range(1, 8)]
        bad = self._board_screen(lines, drop={2})
        with self.assertRaises(main_tdashboard.compat.CompatError) as ctx:
            self._run([bad], lines)
        self.assertIn("missing", str(ctx.exception))

    def test_retry_recovers_from_a_dropped_record(self):
        """First attempt loses a record; the retry succeeds."""
        lines = ["USER PID"] + [f"root {i} proc-{i:03d}-padding-padding"
                                for i in range(1, 8)]
        bad = self._board_screen(lines, drop={2})
        good = self._board_screen(lines)
        got = self._run([bad, good], lines)
        self.assertEqual(got.splitlines(), lines)

    def test_empty_output_says_so_instead_of_blaming_noise(self):
        """A command that prints nothing is the caller's bug, not noise."""
        empty = self._board_screen([])
        with self.assertRaises(main_tdashboard.compat.CompatError) as ctx:
            self._run([empty], [])
        self.assertIn("produced no output", str(ctx.exception))


class WaitPaneIdle(unittest.TestCase):
    """One primitive for "block until the pane's job finishes".

    Callers kept writing their own `while ... sleep` loops, and they failed the
    same ways each time: polling a marker that can never arrive, no failure
    condition for a launcher that died, and no output until the loop ended. That
    is why an interrupted run looked like a 25-minute hang and a finished build
    was still being waited on.

    `wait_pane_idle` is built on `at_end`, so the fakes below stand in for the
    two things the loop actually consults: `at_end` (the readiness oracle, whose
    own behaviour is covered by the `AtEnd`/`TerminalHost` tests) and
    `termstate.launcher_exited`.
    """

    def _run_with(self, states, launcher=None, terminal_host=False):
        """Drive wait_pane_idle through `states`, then a terminal one."""
        seq = list(states)

        def fake_at_end(pane, **kw):
            return seq.pop(0) if seq else True

        saved = {
            "at_end": main_tdashboard.at_end,
            "is_terminal_host": termstate.is_terminal_host,
            "launcher_exited": termstate.launcher_exited,
            "capture_pane": main_tdashboard.compat.capture_pane,
            "describe": termstate.describe,
        }
        main_tdashboard.at_end = fake_at_end
        termstate.is_terminal_host = lambda t: terminal_host
        termstate.launcher_exited = lambda t, **kw: launcher
        termstate.describe = lambda t, **kw: "stub: still busy"
        main_tdashboard.compat.capture_pane = (
            lambda pane, start=None, end=None: ["", "done", ""])
        self.addCleanup(setattr, main_tdashboard, "at_end", saved["at_end"])
        self.addCleanup(setattr, termstate, "is_terminal_host",
                        saved["is_terminal_host"])
        self.addCleanup(setattr, termstate, "launcher_exited",
                        saved["launcher_exited"])
        self.addCleanup(setattr, termstate, "describe", saved["describe"])
        self.addCleanup(setattr, main_tdashboard.compat, "capture_pane",
                        saved["capture_pane"])

        class Pane:
            pane_id = "%0"

        return main_tdashboard.wait_pane_idle(Pane(), timeout=2, poll=0.01)

    def test_returns_when_the_job_finishes(self):
        self.assertEqual(self._run_with([False, False]), "done")

    def test_returns_when_the_launcher_exited(self):
        self.assertEqual(self._run_with([False], launcher="error: interrupted by the user"),
                         "done")

    def test_raises_when_the_budget_runs_out(self):
        with self.assertRaises(main_tdashboard.PaneBusy):
            self._run_with([False] * 100000)

    def test_terminal_host_is_judged_by_probe_not_process_state(self):
        """A booting guest must not be reported idle just because QEMU blocks.

        The old compat implementation returned as soon as
        `state.ready and not is_terminal_host(...)`, which for a terminal host
        was *always* false -- so a booting guest looked finished. Here the host
        flag flips on the same `at_end(probe=True)` path the whole codebase
        uses, so the loop keeps waiting until `at_end` says the screen settled.
        """
        seen = []
        real = main_tdashboard.at_end

        def fake_at_end(pane, **kw):
            seen.append(kw.get("probe"))
            return False if len(seen) < 3 else True

        main_tdashboard.at_end = fake_at_end
        real_host = termstate.is_terminal_host
        termstate.is_terminal_host = lambda t: True
        real_launch = termstate.launcher_exited
        termstate.launcher_exited = lambda t, **kw: None
        real_cap = main_tdashboard.compat.capture_pane
        main_tdashboard.compat.capture_pane = (
            lambda pane, start=None, end=None: ["root@guest:~# "])
        self.addCleanup(setattr, main_tdashboard, "at_end", real)
        self.addCleanup(setattr, termstate, "is_terminal_host", real_host)
        self.addCleanup(setattr, termstate, "launcher_exited", real_launch)
        self.addCleanup(setattr, main_tdashboard.compat, "capture_pane", real_cap)

        class Pane:
            pane_id = "%0"

        out = main_tdashboard.wait_pane_idle(Pane(), timeout=2, poll=0.01)
        self.assertEqual(out, "root@guest:~#")
        self.assertTrue(all(p is True for p in seen),
                        "a terminal host must always be probed")


class StreamScriptGrouping(unittest.TestCase):
    """The pipe must apply to the whole command, not its last statement.

    `_stream_script` interpolated inner_cmd bare in front of `| base64 ...`, so
    `printf L1; echo; printf L2` captured only the final `printf`. Everything
    before it printed to the terminal and was lost, and the reader reported
    "the command produced no output" -- which reads as a broken probe.
    """

    def test_semicolons_are_grouped_under_one_pipe(self):
        script = main_tdashboard._stream_script("echo A; echo B")
        self.assertIn("{ echo A; echo B; } | base64", script)

    def test_a_single_command_is_still_grouped(self):
        self.assertIn("{ true; } | base64",
                      main_tdashboard._stream_script("true"))


class LauncherExited(unittest.TestCase):
    """A foreground launcher that died must not read as "ready".

    The HAT runs its guest through `nixos-shell`. Ctrl-C in that pane prints
    `error: interrupted by the user` and returns to the shell it was launched
    from. Every other detection path asks "is the foreground program blocked
    reading the terminal", which is true of that idle shell -- so a crashed run
    reported READY and the caller polled for a guest that could never appear.
    Measured 2026-11-12: `start cobalt` waited out a 1500 s timeout.
    """

    def _with_screen(self, lines):
        text = "\n".join(lines)

        class StaticSource:
            def run(self, *args):
                return 0, text, ""

        real = termstate.tmux_source
        termstate.set_tmux_source(StaticSource())
        self.addCleanup(termstate.set_tmux_source, real)
        return termstate.launcher_exited("%0")

    def test_interrupted_launcher_is_reported(self):
        marker = self._with_screen([
            "$ nixos-shell ./cobalt.nix",
            "error: interrupted by the user",
            "$ ",
        ])
        self.assertEqual(marker, "error: interrupted by the user")

    def test_a_running_launcher_is_not_reported(self):
        self.assertIsNone(self._with_screen([
            "$ nixos-shell ./cobalt.nix",
            "[17/21 built, 3 copied (13.7 MiB)]",
        ]))

    def test_a_guest_at_its_prompt_is_not_reported(self):
        """The normal running state: the guest shell, nothing interrupted."""
        self.assertIsNone(self._with_screen([
            "$ nixos-shell ./cobalt.nix",
            "root@isp-cobalt:~# ",
        ]))

    def test_a_previous_runs_interrupt_is_not_reported(self):
        """Scrollback from a dead run must not condemn the current one.

        The pane is reused: an interrupted run leaves its message there, and the
        next `start` types a new launch line below it. A plain substring search
        reported the old interruption against the fresh build.
        """
        self.assertIsNone(self._with_screen([
            "$ nixos-shell ./cobalt.nix",
            "error: interrupted by the user",
            "$ nixos-shell ./cobalt.nix",
            "[17/21 built, 3 copied (13.7 MiB)]",
        ]))

    def test_killed_by_signal_is_reported(self):
        self.assertEqual(
            self._with_screen(["$ nixos-shell ./x.nix",
                               "error: killed by signal 9"]),
            "error: killed by signal",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
