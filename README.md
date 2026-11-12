WIP.

# dashboard in tmux

## Table of contents
- [Description](#description)
- [Installation](#installation)
- [Usage](#usage)
- [Running a session file unattended (no REPL)](#running-a-session-file-unattended-no-repl)
- [Reading long output (serial consoles)](#reading-long-output-serial-consoles)

## Description

People who do not like to type repeating themselves in CLI applications might like this project.

You can send files to your tmux panes or you could use the libtmux in cli. 

In the `scripts` folder are a few examples of how you can use the tmux spawner these are included:
  
 - programming: 
   - ipython3 (with errors)
   - php (with errors)
   - powershell (with errors)
 - socat
   - setup a listener
   - rev shell to yourself
 - vim
   - edit a file in vim, safe it under /tmp/testing
   - cat the file

In the configuration write_cfg.py, you can change the config.

## Installation
#### 1. Run the following line in your terminal
```bash 
# This can be used to generate multiple sessions
unset $TMUX
cd /tmp
git clone https://github.com/esp0xdeadbeef/dashboard.git
cd dashboard
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

## Usage
### From the command line:

option 1 open tmux:
```bash
export dashboard_path="/tmp/dashboard"
pip3 install -r $dashboard_path/requirements.txt
ipython3 $dashboard_path/main_tdashboard.py -i -- $dashboard_path/scripts --session-file $dashboard_path/scripts/1_session.py
```


```bash
terminal 2) open the cli (option 2):
alias spawn-tmux-session='
tmux kill-server
sleep 0.2
export dashboard_path="/opt/dashboard"
export scripts_path="$dashboard_path/scripts"
tmux new-session -t spawn-all\; send-keys "
if ! [ -d $dashboard_path/venv ]; 
then 
  python3 -m venv $dashboard_path/venv
fi
source $dashboard_path/venv/bin/activate
pip3 install -r $dashboard_path/requirements.txt
ipython3 $dashboard_path/main_tdashboard.py -i -- $scripts_path --session-file $scripts_path/1_session.py" C-m
'
#and use:
spawn-tmux-session
# whenever you want to spawn the tmux-dashbaord.
```

### Running a session file unattended (no REPL)

For CI, an agent, or a one-shot deploy you do **not** want the `-i` REPL.
Drop `-i`: the dashboard spawns every `spawn_*` in the session file and
returns. `scripts` is a **positional** argument, so put it after the flags:

```bash
tmux-dashboard --target 100.64.0.18:sudo scripts \
    --session-file ./scripts/smoke.py
echo "exit=$?"
```

Things the interactive examples above do not make obvious:

* **`-i` needs a real TTY.** Piping into it (`printf 'a\n' | tmux-dashboard -i
  …`) crashes with `EOFError: EOF when reading a line` — use the
  non-interactive form above instead.
* **The session name is the `spawn_` suffix.** `spawn_smoke()` spawns a
  session named `smoke`; the runner looks that exact name up afterwards. A
  file whose function is `spawn_test` but which calls `renew_session("smoke")`
  will not be found. Keep the two names identical.
* **`dashboard: no tmux session named '<x>'` is normal on a first run.** It is
  printed before the spawn happens; it is not an error. (See
  `BUG-6003660b-…` — it should be silent.)
* **A pane must keep an interactive shell alive.** If a pane's shell exits
  (e.g. it ran a plain non-interactive command and returned), tmux reaps the
  session; check for it with `tmux list-sessions` (or the target's
  `sudo tmux list-sessions`) rather than trusting the exit code. Set
  `remain-on-exit`, or keep the pane at a shell prompt, if you need to read its
  output afterwards.
* **The runner does not surface a long command's exit status.** Record it in
  the pane yourself and read it back, e.g. finish the command with
  `echo EXIT=${PIPESTATUS[0]}`, then `pane_capture()`/`pane_stream()` the pane.

## Targets: driving tmux somewhere else

The same session files work against a tmux server that is **not** your local
one, using `--target` (or `$DASHBOARD_TARGET`):

```bash
# this machine, your tmux (the default)
tmux-dashboard -i scripts --session-file scripts/1_session.py

# `sudo tmux` on this machine: panes are root's
tmux-dashboard -i --target local:sudo scripts --session-file ./session.py

# your tmux here, but every pane runs `sudo -i`
tmux-dashboard -i --target local:sudo-login scripts --session-file ./session.py

# a host over ssh (~/.ssh/config applies: keys, ProxyJump, ControlMaster)
tmux-dashboard -i --target l-portal scripts --session-file ./session.py

# `sudo tmux` on that host
tmux-dashboard -i --target 100.64.0.16:sudo scripts --session-file ./s.py

# a *named socket*: tmux -L NAME
tmux-dashboard --target l-portal,sock=dbg ...

# a *socket path*: tmux -S PATH, for root-owned servers such as
# nixos-shell VMs (/run/nixos-shell/NAME.tmux)
tmux-dashboard -i \
  --target '100.64.0.16:sudo,sock=/run/nixos-shell/s-test.tmux' \
  scripts --session-file ./vm_session.py
```

Check a target before trusting a session to it:

```bash
tmux-dashboard --check --target '100.64.0.16:sudo,sock=/run/nixos-shell/s-test.tmux' scripts
```

```
target: 100.64.0.16:sudo,sock=/run/nixos-shell/s-test.tmux via ssh 100.64.0.16 as root socket /run/nixos-shell/s-test.tmux
  tmux:  ok (1 session(s): vm)
  /proc: ok (RemoteProc: pid 1 -> systemd, wchan available)
  host:  s-sigma
```

### How it works, and what it does not do

Nothing is installed on the remote host. There is no agent, no daemon and no
extra channel:

* **tmux calls** go through a small local `tmux` shim that re-invokes
  `ssh host tmux …` (see `remote.make_tmux_shim`). Every argument is
  `shlex.quote`d, because ssh joins its arguments into one string for the
  remote login shell -- so targets and script lines containing spaces, `$` or
  backticks survive intact.
* **Readiness detection** needs `/proc` of the processes that own the panes.
  For a remote host that means one shell round-trip that dumps the process
  table (`termstate.RemoteProc`); for `:sudo` targets the same query runs under
  `sudo -n`, because the panes are root's. The *decision* logic is unchanged
  and runs locally, so a remote pane is classified exactly like a local one.
* **Prompt detection is learned, not configured.** A prompt only needs to be
  in `prompts.txt` if it cannot be detected from process state. For panes that
  *host* another terminal (a QEMU serial console, `screen`, a nested tmux) the
  state is always "blocked on the tty", so the screen decides -- and the
  prompt is learned from it: once a bare Enter leaves the pane redrawn
  identically, the last line *is* the prompt, and it is recorded (generalised
  over time/host/index) for the rest of the run. New prompt styles therefore
  need no code change.
* **A pager is not a shell.** `git log`, `man`, a long `--help` leave `less`
  (or `more`/`most`) blocked on the tty, which process state reads as "wants
  input" -- but a shell command typed there is a *search* or a *motion*, so it
  never runs. That is caught on the process name (`termstate.PAGERS`), not on
  the screen: `git log` fresh in `less` shows the top of the page with no
  `--More--`/`:` yet, so the screen table would miss it. The pane is reported
  as an unsafe "pager" prompt, so `at_end`/`wait_pane_idle` refuse to type
  into it. Quit the pager first.

Requirements: `ssh host true` must work without a prompt (BatchMode), and
`sudo -n` must succeed for `:sudo` targets. If sudo cannot work
non-interactively the dashboard says so instead of hanging.

If `/proc` cannot be read on the target (no ssh, sudo refused), the dashboard
says so and falls back to matching the on-screen prompt, which is weaker: a
pane running a silent reader (`cat`, `nc`) looks busy. Use `# wait_untill=`
directives in that case.

## Reading long output (serial consoles)

`get_output()` / `pane_capture()` read the **screen**, which is one windowful
(~36 rows) and is fine for a shell that prints a few lines. They are the wrong
tool for anything long, and outright unsafe on a serial console:

* a `ps auxwwwww` with ~190 rows comes back as 14 lines, with nothing to say
  it was truncated;
* a UART has **kernel messages interleaved into the stream at arbitrary
  points**, mid-line (`mt7996e … Failed to del Host Multicast Database`), so a
  transfer over `tio`/`minicom` is never clean; and
* filtering the junk out does not work. Stripping non-base64 characters
  removes the junk *and the evidence*, so a corrupted transfer decodes into a
  plausible **wrong** answer.

Use `pane_stream()` instead:

```python
def spawn_main():
    main_session = renew_session("main")
    pane = compat.active_pane(main_session)
    text = pane_stream(pane, "ps auxwwwww", location="/tmp/ps.txt")
```

It frames the transfer: the board emits `<seq>:<total>:<base64>:<md5>` per
line, so

* every record is verifiable on its own, and
* a **lost or split record shows up as a gap** in the sequence.

That second point is the one that is easy to get wrong. A checksum per line is
*not* enough: when junk splits a record in two, each half is still a
self-consistent `payload|checksum` pair, so validation passes on fragments and
the result is half-corrupted data. Only `seq`/`total` expose that. (A split
takes `ps`'s own wrapping with it -- measured on `l-portal`, 40 of 99 rows were
malformed and every one of them validated.)

If records are still missing after `attempts` (default 3), `pane_stream()`
**raises** rather than returning short data, because a truncated listing looks
exactly like a correct short one. On a very noisy console, quiet the log first:

```sh
dmesg -n 1     # on the host whose console is spamming
```

