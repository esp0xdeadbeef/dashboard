# BUG: a booting guest is reported as "launcher exited", because the guard only sees a live terminal host

**Severity:** HIGH — `start` fails on a run that is actually booting, and `stop` then reports
"nothing was running" while the VM is alive.

Observed 2026-11-12, repeatedly, on `hat-isp.py start cobalt`.

## Symptom

    $ hat-isp.py start cobalt
      network-renderer-wireguard: updated
    guest did not come up; the launcher exited first. Last line:
    '/nixos.org/manual/nixos/stable/options.html#opt-system.stateVersion.'
    (an interrupted run reports 'error: interrupted by the user')

The pane at that moment:

    [  OK  ] Reached target Login Prompts.
    <<< Welcome to NixOS 26.05pre-git (x86_64) - hvc0 >>>
    isp-cobalt login: root (automatic login)

— a guest in the middle of booting. Moments later it was at `root@isp-cobalt:~/` and every
acceptance check passed.

## Mechanism

`launcher_exited` returns a marker only if it appears after the last `LAUNCH_LINES` entry,
and has a guard for exactly this case:

    if _terminal_host_running(target):
        return None
    return marker

`_terminal_host_running` deliberately scopes to **this pane's process ancestry**, and says
so: "a live QEMU that the pane can still see (its own child, or the wrapper above it) is the
only evidence the pane itself can offer."

During early boot the pane's chain does not yet include the QEMU, so the guard answers
False, the old marker in scrollback wins, and the run is declared dead. Later, once
`chain=[zsh > .nixos-shell-wr > .qemu-system-x8]`, the same call correctly returns None:

    launcher_exited: None
    terminal_host_running: True

So the verdict depends on **when** it is asked, and `wait_guest` asks it in a loop from the
first instant of the run.

## Why the scrollback marker is there at all

The pane is reused across runs. A previous interrupted run left
`error: interrupted by the user` above the current output, and the "after the last launch
line" filter cannot help because the launch line itself has scrolled out of the 60-line
window by the time a boot is underway.

## What is needed

1. `launcher_exited` must not consult scrollback alone. The authoritative question is "does
   a launcher process for this session still exist", which the pane's chain answers only
   while QEMU is a descendant -- and it is not one during early boot.
2. The caller (`wait_guest`) should treat "a launcher is running" as "keep waiting", and only
   "no launcher anywhere and a marker in scrollback" as an exit. The HAT already has
   `site_vm_pid` for the machine-wide question; the dashboard needs the equivalent for a
   pane's session (tmux pane pid -> descendants, plus the wrapper).
3. A scrollback marker should carry its age or its position relative to the *current*
   session start, not be matched by bare substring at all.

## Reproduce

    hat-isp.py start cobalt     # let a previous run be interrupted first (Ctrl-C in the pane)
    hat-isp.py stop cobalt
    hat-isp.py start cobalt     # during the boot window, this reports "launcher exited"

## Note

Nothing is wrong with the site, the model or the renderer. The guest in the failing run
reached its prompt and passed the acceptance checks; only the verdict was wrong.

## Resolution (FIXED)

`launcher_exited` now asks the right question before honouring a scrollback
marker: `_launcher_running()` looks for a launcher process (nixos-shell /
nix-shell / nix-build / nixos-build-vms / vagrant) or a terminal host anywhere in
the pane's process tree -- its ancestry **and its descendants**. Descendants are
what the previous guard missed: during early boot QEMU is not yet an ancestor of
anything the pane reports (chain is `[zsh]` / `[zsh > .nixos-shell-wr]`), so an
ancestry-only test answered False and a stale marker condemned a guest that was
mid-boot.

Scope stays this pane's subtree, not the machine (tmux/screen/socat are terminal
hosts and exist everywhere). A VM orphaned by a killed session remains invisible
from the pane by construction -- reaping that is `start`/`stop`'s job.

Covered by `LauncherExited::test_a_booting_guest_is_not_reported_exited`.
