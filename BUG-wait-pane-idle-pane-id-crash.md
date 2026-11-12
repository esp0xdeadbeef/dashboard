# BUG: `wait_pane_idle` accepts a pane id string but crashes resolving it

**Severity:** MEDIUM — the documented calling convention fails; callers must know
an undocumented requirement.
**File:** `main_tdashboard.py` (`wait_pane_idle`, `at_end`, `_stable_prompt`) and
`compat.py` (`capture_pane`)
**Status:** FIXED

## Symptom

`wait_pane_idle` documents that it takes a pane object *or* a pane id string:

```python
# main_tdashboard.py, wait_pane_idle
target = pane.pane_id if hasattr(pane, "pane_id") else str(pane)
```

Passing the id string — the form the docstring suggests, and the only form
available when a session file has finished and the caller is reading panes back
by id — raises:

```
AttributeError: 'str' object has no attribute 'capture_pane'
```

## Exact reproduction

```
$ cd ~/github/dashboard && source venv/bin/activate
$ python3 - <<'PY'
import sys, traceback
sys.path.insert(0,".")
import main_tdashboard as d
try:
    d.at_end("%167", probe=True)
except Exception:
    traceback.print_exc()
PY
Traceback (most recent call last):
  File "<stdin>", line 5, in <module>
  File "main_tdashboard.py", line 753, in at_end
    stable = _stable_prompt(pane, debugging=debugging)
  File "main_tdashboard.py", line 877, in _stable_prompt
    before = prompt_line()
  File "main_tdashboard.py", line 851, in prompt_line
    for line in reversed(compat.capture_pane(pane)):
  File "compat.py", line 538, in capture_pane
    return pane.capture_pane()
AttributeError: 'str' object has no attribute 'capture_pane'
```

The same failure reaches `wait_pane_idle` on every pane:

```
%167 -> busy/err: AttributeError("'str' object has no attribute 'cmd'")
%168 -> busy/err: AttributeError("'str' object has no attribute 'cmd'")
...
```

(The `'cmd'` wording is libtmux's; the underlying cause is the same — a string
where a pane object is expected.)

## Why it matters

A caller that spawns panes and later wants to block on them has only ids: a
session file's libtmux handles are stale as soon as `renew_session` recreates
the session. So the one documented way to wait on a pane is exactly the way that
crashes.

## Suggested fix

Resolve once, at the boundary, and pass the object down:

```python
def _as_pane(pane):
    if hasattr(pane, "pane_id"):
        return pane
    return compat.pane_by_id(str(pane))   # panes raised -> re-resolve live pane
```

then call `at_end(_as_pane(pane), ...)` and use `_as_pane(pane).pane_id` for
`target`. `compat.pane_by_id` already exists and re-resolves from the live
server, which is why the stale-handle problem does not apply to it.

## Workaround

Pass a live libtmux pane object, e.g. `compat.pane_by_id("%167")`, rather than
the id string. Verified by reading pane contents with
`tmux capture-pane -p -t <id>` in the meantime.

## Resolution (FIXED)

`main_tdashboard._as_pane()` resolves a pane id string to a live libtmux Pane
via `compat.pane_by_id`, called once at the boundary of both `at_end` and
`wait_pane_idle`. Passing `%167` now works; a bogus id raises `CompatError`
(`no such pane ...`) instead of `AttributeError`. Covered by
`test_detection.PaneArgAcceptance`.
