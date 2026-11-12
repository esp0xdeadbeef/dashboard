# BUG: the HAT probe reads empty output as failure, and cannot tell it from success

Written from tmux scrollback during a cobalt HAT run, 2026-11-12.

## Symptom

`hat-isp.py core cobalt` printed

    --- interface ---
    <no output>
    --- default ---
    <no output>
    --- ping ---
    <no output>
    FAIL: interface, default, ping

while the same commands, run one at a time by hand, succeeded. The acceptance probe
declared a working core broken, twice in one session, and once led me to blame a renderer
commit that was fine.

## What the scrollback actually shows

```
root@isp-cobalt:~/ > echo STREAM..._START; nixos-container run core -- sh -c 'if ip -4 -
br a show wan | grep -q inet && ip -4 route show default | grep -q default; then echo
ADDRESSED; else echo NOT-ADDRESSED; fi' | base64 -w 60 > /tmp/.dash_stream; ...
STREAM..._START
1:1:Tk9ULUFERFJFU1NFRAo=:cb6192ef
STREAM..._END
```

`Tk9ULUFERFJFU1NFRAo=` is base64 for `NOT-ADDRESSED`. So the pipeline worked, the record was
produced and checksummed, and the answer was simply wrong. Checking the container directly:

    core$ ip -4 -br a show wan   -> wan@if76 UP 192.0.2.102/23
    core$ ip -4 route show default -> default via 192.0.2.1 dev wan

both conditions TRUE, while the compound test reported NOT-ADDRESSED.

## The bug this file is about

Before the change above, the same block had been typed four times with **no records at
all** between the markers:

```
STREAM24988601794513280273_START
STREAM24988601794513280273_END
root@isp-cobalt:~/ >
root@isp-cobalt:~/ > echo STREAM24988601794513281378_START; ... (identical)
STREAM24988601794513281378_START
STREAM24988601794513281378_END
```

The command was a bare compound test, which prints nothing when it succeeds. `pane_stream`
refuses empty output on purpose -- `"the command produced no output"` -- so **success and
failure both arrive as an error**, and the retry loop could not converge. Four retries, four
identical empty blocks, each one a correct report that the command said nothing.

`pane_stream` is right and the caller was wrong: a probe must emit a verdict, not rely on
silence. Fixed by printing `ADDRESSED` / `NOT-ADDRESSED`.

## Second bug: output can precede the echoed command line

`nixos-container run` interleaves its output with the shell's echo. The scrollback shows

```
INNER
__MARK_E
root@isp-cobalt:~/ >
root@isp-cobalt:~/ > echo __MARK_B; nixos-container run core -- echo INNER; ...
__MARK_B
```

The body sits **above** the start marker. Six successive hand-written parsers in
`hat-isp.py` each guessed a different relationship between body and markers and each broke
on a case the previous one had not seen. `pane_stream` already solves this with
sequence-numbered, checksummed records; `hat-isp.py` now delegates to it instead of
re-implementing it.

## Third bug: a healthy build reported as a dead run

`state` printed `READY` for a pane whose guest had exited, because READY only means "the
foreground program is blocked reading the terminal" -- equally true of the idle host shell
left behind by a cancelled `nixos-shell`. `start` then typed a launcher line into that
shell. `state` now distinguishes guest present / starting (and what the launcher is doing)
/ launcher exited, and `start` waits for a live shell before sending anything.

## The bug that caused the "crashes"

`error: interrupted by the user` in the pane was not a person pressing Ctrl-C. **Three**
`hat-isp.py start cobalt` processes were alive at once, left by backgrounded launches that
were never reaped, each typing `nixos-shell ...` into the same pane and sending Ctrl-C when
it gave up. Every run killed the previous one's build. `start` now holds an `flock` per site
and refuses to run concurrently.

## Lesson for this repository

A probe has three outcomes, not two: succeeded, failed, and **said nothing**. Anything that
conflates the third with the second will retry forever or report a false failure. Emit a
verdict in the command itself, and let the reader refuse genuine silence.
