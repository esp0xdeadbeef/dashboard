# BUG-checked-cmd-concatenates-onto-the-previous-command

`checked_cmd()` typed its line before the shell had consumed `panes_from_list`'s
trailing Enter, producing a command that does not exist.

## Reproduced

```python
session = renew_session("ciwait")
panes_from_list(session, ["true"], start_directory=REPO)   # send_enter=True
pane = compat.active_pane(session)
checked_cmd(pane, "cd /repo && gh run watch 1 --exit-status; ...", last_row_send="")
```

The pane shows the two commands joined:

```
└─[%] truecd /home/deadbeef/github/network-labs && gh run watch 43320670072 --ex
it-status; printf '\n=== ci exit=%s\n' "$?"
zsh: command not found: truecd
=== ci exit=127
```

`checked_cmd` still reported completion, because its end marker was printed by
the shell afterwards -- so the caller gets `exit=127` and no explanation.

## Why

`panes_from_list` -> `send_keys_to_pane` returns after a fixed
`time_out_unchecked=0.1` (`main_tdashboard.py:342`), with no confirmation that
the trailing Enter (`send_enter_last_row=True`) was consumed by the shell.
`checked_cmd` then waits for `at_end()`, which is true while the shell is still
busy digesting that Enter, and types immediately.

So the failure needs two things that are both normal: a `spawn_*` that seeds a
pane with a command, and a `checked_cmd` call in the same `spawn_*`.

## Suggested fix (either)

1. After sending the last row, have `send_keys_to_pane` wait for the pane to
   return to a prompt *before* returning, rather than a fixed 0.1s; or
2. Have `checked_cmd` begin with `send_keys(pane, "C-u")` so any half-typed line
   is discarded before its own line is typed; or
3. Document that a `spawn_*` must seed the pane with `""` when it intends to
   call `checked_cmd`.

`scripts/ci_wait_session.py` now seeds with `""` (option 3) and works.

## Severity

The failure mode is a plausible-but-wrong result (`exit=127`) that looks like
the watched job failed, rather than like a harness bug.
