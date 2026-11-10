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

    def test_qemu_is_a_terminal_host(self):
        self.assertTrue(termstate._is_terminal_host("qemu-system-x8"))
        self.assertFalse(termstate._is_terminal_host("bash"))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
