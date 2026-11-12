# BUG: a running VM is reported as "launcher exited", and it keeps the image locked

**Severity:** HIGH — a healthy VM becomes unstartable, and the error names the wrong thing.

Observed 2026-11-12 driving the cobalt HAT (`hat-isp.py start cobalt`).

## Symptom

`start` reported

    guest did not come up; the launcher exited first. Last line:
    '/nixos.org/manual/nixos/stable/options.html#opt-system.stateVersion.'
    (an interrupted run reports 'error: interrupted by the user')

Running the fixture directly exited 1 with

    qemu-system-x86_64: -drive cache=writeback,file=.../isp-cobalt.qcow2,...
      Failed to get "write" lock
    Is another process using the image [.../isp-cobalt.qcow2]?
    EXIT=1

## What was actually true

A **live** QEMU with a live `nixos-shell` parent:

    $ ps -o pid,ppid,stat,etime -p 3074398
      3074398  3030926  Sl+  05:37      qemu-system-x86_64 ... isp-cobalt.qcow2
    $ ps -o cmd -p 3030926
      .../nixos-shell [.../GAMP/HAT/egress-chain/isp/cobalt.nix]

Nothing was wrong with the fixture, and the guest was reachable. A previous session's VM had
outlived its tmux session.

## Why `start` misread it

`start` decides a run is over from `termstate.launcher_exited`, which looks for a marker in
the pane's scrollback. After a session is killed the pane is replaced by a fresh shell whose
scrollback still carries the OLD run's `error: interrupted by the user`, and the liveness
question is asked of the pane rather than of the machine. A VM whose pane was replaced is
indistinguishable, from inside the new pane, from one that never started.

## The second half: nothing reaps a VM whose pane is gone

`stop` sends `poweroff` into the pane and waits for the host shell. If the pane is gone,
`stop` has nothing to talk to and the VM survives, holding `isp-<site>.qcow2`. The next
`start` then fails at QEMU's write-lock check, which names the image and not the orphan.

## What is needed

1. `start` and `stop` should reason about the **VM process**, not only the pane: a
   `qemu-system` whose command line carries `isp-<site>.qcow2` means the run is alive,
   whatever any pane shows.
2. The image is a per-site singleton, so holding it *is* the lock. A write-lock failure
   should say "a VM for this site is already running (pid N)", not "failed to get write
   lock".
3. `stop` should reap by process when the pane is gone.
4. `state` must not report `guest: GONE` while `qemu-system ... isp-<site>.qcow2` is alive.

## Reproduce

    hat-isp.py start cobalt              # boots a VM in tmux session isp-cobalt
    tmux kill-session -t isp-cobalt      # the VM outlives its pane
    hat-isp.py start cobalt              # "launcher exited", then QEMU write-lock error

## Workaround

    pkill -f 'qemu-system.*isp-cobalt.qcow2'
    hat-isp.py start cobalt
