# BUG-ci-watch-reports-success-when-gh-fails

`ci_watch_session.py`'s default watch command reports `ci exit=0` when `gh run
list` failed and no run was ever watched.

## Reproduced

```bash
gh run list --limit 1 --json databaseId --jq '.[0].databaseId' \
  | xargs -r gh run watch --exit-status
# gh: HTTP 403: API rate limit exceeded ...
# (pane then prints) === ci exit=0
```

Measured on 2026-11-12 with the GitHub core quota exhausted. The pane showed the
403 and then a **successful** exit.

## Why

`xargs` exits 0 when it receives no input: `gh run list` fails, produces no
`databaseId`, and `xargs -r` has nothing to run. The pipeline's exit status is
`xargs`'s, so the failure of the first stage disappears:

```bash
false | xargs -r true; echo $?          # 0  -- failure masked
set -o pipefail; false | xargs -r true; echo $?   # 1  -- failure reported
```

## Fix

`scripts/ci_wait_session.py` and `scripts/ci_watch_session.py` now begin the
command with `set -o pipefail`, so the `gh run list` failure fails the watch.

## Severity

The worst kind of wrong answer for a watcher: a run that was never observed is
reported as having succeeded. A caller that trusts `ci exit=` will treat a
red/unwatched build as green.
