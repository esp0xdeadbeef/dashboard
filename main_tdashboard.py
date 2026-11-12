#!/usr/bin/env python3
import argparse
import base64
import hashlib
import string
import sys
import re
import shutil
import subprocess
import os
import tempfile
import time

import libtmux

import compat
import prompts
import remote
import termstate


def run(cmd_args, check=True, capture=True):
    """Run a command as an argument list (never a shell string).

    Replaces the original os.popen()/os.system() calls, which concatenated
    paths into a shell command and swallowed all errors.
    """
    result = subprocess.run(
        cmd_args,
        capture_output=capture,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd_args)}"
            + (f"\nstderr: {result.stderr}" if result.stderr else "")
        )
    return result


def natural_sort(l):
    # used from  here:
    # https://stackoverflow.com/questions/4836710/is-there-a-built-in-function-for-string-natural-sort
    def convert(text):
        return int(text) if text.isdigit() else text.lower()

    def alphanum_key(key):
        return [convert(c) for c in re.split('([0-9]+)', key)]
    return sorted(l, key=alphanum_key)


def get_file_content(file_path):
    with open(file_path, 'r') as f:
        return f.read()


def get_scripts_location(path):

    if os.path.exists(path):
        return True
    else:
        return False


def get_dir_session_files(scripts_location, session_name=None):
    if not os.path.isdir(scripts_location):
        raise FileNotFoundError(
            f"scripts directory not found: {scripts_location}")
    cmd = ["ls", "-vA", scripts_location]
    os_ex = run(cmd).stdout.split()
    files = [i for i in os_ex if i]
    if session_name:
        files = [i for i in files if session_name in i]

    files_to_get = {}

    for f in files:
        curr_file = '_'.join(f.split('_')[:-1])
        files_to_get[curr_file] = f"{scripts_location}/{f}"

    return files_to_get


def list_potentional_sessions(all_functions):
    spawn_list = []
    for _function in all_functions:
        if 'spawn_' in _function:
            spawn_list.append(_function)
    return spawn_list


def renew_session(name,
                  keep_session=False,
                  start_directory='~'):
    """ 
    Returns an session object
    """
    if not isinstance(name, str):
        raise TypeError("name must be a str")
    session = compat.get_session(server, name)
    if keep_session:
        return session
    if session is not None:
        compat.kill_session(session)
    try:
        session = server.new_session(name,
                                     start_directory=start_directory)
    except ValueError:
        pass
    if session is None:
        # some tmux versions report an otherwise-successful creation here.
        session = compat.get_session(server, name)
    return session


def background_task_in_pane(pane,
                            wait_time=0.5,
                            debugging=False):
    compat.send_keys(pane, 'C-z')
    wait_time_total = 0
    backgrounded_task = False
    interpreter = False
    while wait_time_total < wait_time and not(backgrounded_task) and not(interpreter):
        last_cap = pane_capture(pane, debugging=debugging)[-1].lower()
        if debugging:
            print("{background_task_in_pane}", end=", ")
            print("trying to find background (y or n question) or interpeter in pane")
        if "background" in last_cap or "y/N" in last_cap:
            backgrounded_task = True
            if debugging:
                print("{background_task_in_pane}", end=", ")
                print("found background in text.")
        for i in interpreters:
            if i.lower() == last_cap and "Z^" not in last_cap:
                if debugging:
                    print("{background_task_in_pane}", end=", ")
                    print(f"({i.lower()} == {last_cap})" +
                          " found interpreter in text.")
                interpreter = True
        wait_time_total += (wait_time / 10)

        time.sleep((wait_time / 10))
    if backgrounded_task:
        time.sleep(1)
        compat.send_keys(pane, 'y')
        time.sleep(1)
        compat.send_keys(pane, "Enter")
        time.sleep(1)


def get_output(pane,
               last_command="dump_all",
               location="/tmp/tmux_output.txt",
               debugging=False,
               sleep_time=0.2,
               max_size=10**8
               ):

    res = pane_capture(pane, size=max_size)

    if not(last_command == "dump_all"):
        for counter, i in enumerate(res[::-1]):
            if last_command in i:
                res = res[(len(res) - counter - 1):]
                if debugging:
                    print(f'Breaking because found {last_command}')
                break
    if debugging:
        print(f'writing file {location}, from keyword {last_command}')
    with open(location, 'w') as f:
        f.write('\n'.join(res))
    if debugging:
        print(f"len of res: {len(res)}")
        print("wc output: " + run(["wc", location]).stdout)
    return res


# --------------------------------------------------- checksummed transfer ---
#
# `pane_capture`/`get_output` read the *screen*. That is fine for a shell that
# prints a few lines, and wrong for anything long or noisy:
#
#   * the screen is one windowful (~36 rows), so long output is silently
#     truncated -- a `ps auxwwwww` with 190 rows yields 14;
#   * a serial console (tio, minicom, a UART) has kernel messages interleaved
#     into the stream at arbitrary points, mid-line;
#   * "filter out the junk" does not work. Stripping non-base64 characters
#     removes the junk AND the evidence, so a corrupted transfer decodes cleanly
#     into a plausible wrong answer.
#
# So a long read is framed: every line carries a sequence number, the total, and
# a checksum of its own payload. That makes each record verifiable on its own
# AND makes a lost or split record detectable as a gap.
#
# A per-record checksum alone is NOT enough, which is easy to get wrong: when
# junk splits a record in two, each half is still a self-consistent
# `payload|checksum` pair, so validation passes on fragments and the result is
# half-corrupted data. Only the sequence numbers expose that.
#
# The payload is base64 and the lines are short (-w 60) so that the console
# width cannot auto-wrap a record into two lines at an arbitrary column.
STREAM_RECORD = re.compile(r"^\s*(\d{1,7}):(\d{1,7}):([A-Za-z0-9+/=]{4,}):"
                           r"([0-9a-f]{8})\s*$")


def _stream_script(inner_cmd):
    """Shell that emits <seq>:<total>:<b64-chunk>:<md5> per line of the stream.

    `inner_cmd`'s output is base64-encoded as ONE stream and then wrapped at
    60 columns, so a chunk is mid-stream and only the last one carries
    padding -- decoding must therefore join all chunks first (see
    pane_stream). Wrapping matters because the console is ~124 columns wide
    and would otherwise insert its own breaks at arbitrary points.

    The md5 is taken over `printf %s "$l" | base64 -w0`, i.e. the chunk
    *re-encoded*, not the chunk text itself. The local side reproduces exactly
    that (`base64.b64encode(payload)`); hashing the chunk directly instead
    validates 0 of N records. Confirmed on the host:
        printf %s cm9vdCAxIGluaXQ= | base64 -w0 | md5sum  ->  ebc79f2d
        printf %s cm9vdCAxIGluaXQ= | md5sum              ->  fb86bd08
    """
    return (
        # Braced, so the pipe applies to the WHOLE command. Interpolated bare,
        # `printf L1; echo; printf L2` became `printf L1; echo; printf L2 |
        # base64 ...` and only the last statement was captured -- every earlier
        # one printed to the terminal and vanished. Measured 2026-11-12:
        # `printf "L1\nL2\n"` worked, `printf L1; echo; printf L2; echo`
        # reported "the command produced no output", and so did a legitimate
        # `echo A; echo B`.
        f"{{ {inner_cmd}; }} | base64 -w 60 > /tmp/.dash_stream; "
        "n=$(wc -l < /tmp/.dash_stream); i=0; "
        "while read -r l; do i=$((i+1)); "
        'echo "$i:$n:$l:$(printf %s "$l" | base64 -w0 | md5sum | cut -c1-8)"; '
        "done < /tmp/.dash_stream"
    )


def pane_stream(pane, inner_cmd, location=None, attempts=3,
                scrollback=12000, debugging=False):
    """Run `inner_cmd` in `pane` and return its complete output, verified.

    Use this instead of `get_output` whenever the output is longer than a
    screen or the pane is a serial console. It is the only read path that is
    correct on a wire, because it does not depend on the screen being clean.

    Returns the decoded text. Raises `compat.CompatError` if every attempt
    leaves records missing -- refusing rather than returning partial data is
    the point: a truncated `ps` listing looks exactly like a correct short one.
    """
    last = "no attempt made"
    for attempt in range(1, attempts + 1):
        marker = f"STREAM{os.getpid()}{int(time.time() * 1000)}"
        compat.send_keys(pane, f"echo {marker}_START; "
                               + _stream_script(inner_cmd)
                               + f"; echo {marker}_END")
        compat.send_keys(pane, "C-m")
        if not wait_untill_msg(pane, f"{marker}_END", timeout=180,
                               time_out=0.5):
            last = "end marker never appeared"
            if debugging:
                print(f"{{pane_stream}} attempt {attempt}: {last}")
            continue

        target = _pane_target(pane)
        rc, out, _ = termstate.tmux_source().run(
            "capture-pane", "-t", target, "-p", "-S", f"-{scrollback}")
        if rc != 0:
            last = "capture-pane failed"
            continue
        lines = out.splitlines()
        ends = [i for i, l in enumerate(lines) if f"{marker}_END" in l]
        if not ends:
            last = "end marker not in capture"
            continue
        end = max(ends)
        starts = [i for i, l in enumerate(lines[:end])
                  if f"{marker}_START" in l]
        body = lines[(max(starts) if starts else 0) + 1:end]

        records, junk = {}, 0
        for line in body:
            m = STREAM_RECORD.match(line)
            if not m:
                junk += 1        # kernel spam or a prompt; harmless
                continue
            seq, total, payload, digest = m.groups()
            # The board hashed `printf %s "$l" | base64 -w0`, i.e. the
            # payload re-encoded as base64 with no trailing newline.
            # Reproducing that byte-for-byte is the whole contract; hashing
            # the decoded bytes instead silently validates 0 of N records.
            want = hashlib.md5(
                base64.b64encode(payload.encode())).hexdigest()[:8]
            if want != digest:
                junk += 1        # a damaged record; its seq will show as a gap
                continue
            records[int(seq)] = (payload, int(total))

        totals = {t for _, t in records.values()}
        if len(totals) != 1:
            # Zero records means the command produced nothing (or failed);
            # several different totals means records from different attempts
            # were mixed. They are different problems and deserve different
            # messages -- the first is usually the caller's command, not noise.
            last = ("the command produced no output" if not totals
                    else f"inconsistent totals {sorted(totals)}")
            if debugging:
                print(f"{{pane_stream}} attempt {attempt}: {last}")
            continue
        total = totals.pop()
        missing = [i for i in range(1, total + 1) if i not in records]
        if debugging:
            print(f"{{pane_stream}} attempt {attempt}: got={len(records)}/"
                  f"{total} junk={junk} missing={len(missing)}")
        if missing:
            last = f"{len(missing)} of {total} records missing"
            continue

        # Join the payloads, then decode once. The board base64-encodes the
        # whole stream and *then* wraps it at 60 columns, so a 60-char chunk
        # is mid-stream and cannot be decoded on its own: only the final line
        # carries the padding. Decoding per line fails with "Excess data after
        # padding" on any multi-line payload. Verified on the board:
        #   printf 'a...a\n' | base64 -w 60  ->  60-char lines + a padded tail.
        text = base64.b64decode(
            "".join(records[i][0] for i in range(1, total + 1)),
            validate=True).decode(errors="replace")
        if location:
            with open(location, "w") as fh:
                fh.write(text)
        return text
    raise compat.CompatError(
        f"pane_stream: could not read {inner_cmd!r} intact after {attempts} "
        f"attempts ({last}). "
        + ("Check that the command exists and prints something."
           if last == "the command produced no output" else
           "The pane's console is too noisy right now; re-run, or quiet the "
           "kernel log with `dmesg -n 1` on that host."))


def send_keys_to_pane(pane,
                      script_content,
                      time_out_checked=0.1,
                      time_out_unchecked=0.1,
                      skip_check_chars="# skip check comming = ",
                      in_file_exec_function="# exec ",
                      append_file="# append ",
                      wait_untill_string="# wait_untill=",
                      safe_last_output_to_file="# safe_last_output_to_file=",
                      bg_task_in_pane="# background task in pane",
                      send_enter_last_row=True,
                      debugging=False):
    """
exercise_pane = compat.require_session(server, 'test')
pane = compat.active_pane(exercise_pane)
send_keys_to_pane(pane, get_file_content(all_files["test"]))
    """
    unchecked = 0
    content = script_content.split('\n')

    last_row_send = ""
    for counter, row_to_send in enumerate(content):
        send_enter = counter != (len(content) - 1) and send_enter_last_row
        if debugging:
            print("{send_keys_to_pane}", end=", ")
            print(f"row_to_send = {row_to_send}", end="; ")
            print(f"unchecked = {str(unchecked)}", end="; ")
            print(f"send_enter = {str(send_enter)}")
        if in_file_exec_function in row_to_send:
            exec_function = row_to_send.split(in_file_exec_function)[1]
            exec(exec_function) in globals(), locals()
            continue
        if bg_task_in_pane in row_to_send:
            background_task_in_pane(pane)
            continue
        if safe_last_output_to_file in row_to_send:
            while not(at_end(pane)):
                print("{send_keys_to_pane}: waiting untill at_end")
                time.sleep(time_out_checked)
                pass
            safe_location = row_to_send.split(safe_last_output_to_file)[1]
            if debugging:
                print(
                    f'safe_location = "{safe_location}", last_row_send  = "{last_row_send}"')
            get_output(pane,
                       last_command=last_row_send,
                       debugging=True,
                       location=safe_location
                       )
            continue
        if append_file in row_to_send:
            file_in_dict = row_to_send.split(append_file)[1]
            if debugging:
                print('trying to add file_in_dict after this line.')
            for row_2_counter, row_in_file in enumerate(get_file_content(get_dir_session_files(args.scripts)[file_in_dict]).split('\n')):
                if debugging:
                    print(f'adding this line now: {row_in_file}')
                content.insert(row_2_counter + counter+1, row_in_file)
            continue
        if skip_check_chars in row_to_send:
            unchecked = int(row_to_send.split(
                skip_check_chars)[1].split('#')[0])
            continue
        if wait_untill_string in row_to_send:
            string_to_wait_for = row_to_send.split(
                wait_untill_string)[1].split('#')[0]
            wait_untill_msg(pane, string_to_wait_for)

            continue
        if row_to_send == "":
            compat.send_keys(pane, row_to_send)
            if send_enter:
                compat.send_keys(pane, "C-m")
                time.sleep(time_out_unchecked)
            if debugging:
                print('Unchecked, it\'s empty.')
        elif unchecked > 0:
            compat.send_keys(pane, row_to_send)
            if send_enter:
                compat.send_keys(pane, "C-m")
                time.sleep(time_out_unchecked)
            if debugging:
                print('Unchecked, requested by user.')
            unchecked -= 1
            last_row_send = row_to_send
        else:
            if debugging:
                print("{send_keys_to_pane}: checked_cmd: ")
            checked_cmd(pane,
                        row_to_send,
                        last_row_send,
                        time_out=time_out_checked,
                        # send_enter_last_row=send_enter,
                        # send_enter=send_enter,
                        debugging=debugging
                        )
            last_row_send = row_to_send
            if debugging:
                print("Checked.")


# Characters that mark a line as terminal echo rather than program output. A
# prompt followed by the typed command contains both the prompt and the text,
# so it must not be treated as evidence that the program produced it.
_ECHO_MARKERS = ("$ ", "# ", "% ", "> ")


def _message_in_output(lines, message):
    """True when `message` appears in pane output, ignoring echoed input.

    Two independent filters, because either alone is defeatable:

    1. A line whose text before the message looks like a prompt (``...$ ...``)
       is the shell echoing the command that was typed.
    2. A line that contains MORE than the bare message is a command line too:
       an `echo` prints exactly `message`, so a line carrying `message` plus
       other text (`sleep 6; echo <message>`) can only be the echo. This also
       catches wrapped echoes, where the terminal broke the line and the prompt
       is no longer visible on the same row -- observed 2026-11-10, which made a
       6-second command look finished in 0.4s.
    """
    for line in lines:
        if message not in line:
            continue
        if line.strip() == message.strip():
            return True
        if any(marker in line[: max(0, line.index(message))] for marker in _ECHO_MARKERS):
            continue
        # Message plus surrounding text is an echo, not program output.
        continue
    return False


def wait_untill_msg(pane,
                    message,
                    time_out=0.2,
                    safe_output=None,
                    timeout=60,
                    raise_on_timeout=False):
    """Block until `message` appears in the pane.

    The original loop never gave up: if the message could not appear (a tool
    that is not installed, a listener that never received its connection) the
    dashboard hung with no output, which looks identical to "still working".
    A bounded wait turns that into a decision.

    Timing out is not automatically an error: a session file may be waiting
    for something that is only logged in passing, and continuing is often
    right. The default therefore warns and returns False, and
    `raise_on_timeout=True` makes it fatal for scripts that need the check to
    mean something.

    The message must appear in the pane's OUTPUT, not in the echo of the
    command that produced it. The terminal echoes every line that is typed, so
    a plain substring search over the whole screen matches the command line
    itself and returns immediately. That turns a wait into a no-op, and it is
    how a check for "is ppp0 up?" once reported UP while the interface did not
    exist: the marker was in the `if ...; then echo <marker>_UP; ...` that had
    just been typed. A line that contains the message *and* is a shell prompt
    echoing input is therefore skipped.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _message_in_output(pane_capture(pane), message):
            return True
        time.sleep(time_out)
    target = getattr(pane, "pane_id", pane)
    tail = [line for line in pane_capture(pane, size=10) if line.strip()][-3:]
    print(f"{{wait_untill_msg}} timed out after {timeout}s waiting for "
          f"{message!r} in {target}")
    for line in tail:
        print(f"    | {line}")
    if raise_on_timeout:
        raise compat.CompatError(
            f"wait_untill_msg: {message!r} did not appear in {target} within "
            f"{timeout}s (last line: {tail[-1] if tail else '<empty>'})")
    return False


def panes_from_list(session,
                    keys_to_send_list,
                    send_enter=True,
                    debugging=False,
                    all_unchecked=True,
                    start_directory=None):
    """Fill one window of `session` with one pane per entry.

    Every split, layout change and keystroke targets a specific window
    (``@N``). Relying on "the session's active window" works locally by luck
    -- you are usually looking at it -- but is wrong on a remote or sudo
    server, where another client may have switched windows, and filling the
    wrong window fails silently.

    Window and pane lookups go through `compat`'s raw tmux helpers rather than
    libtmux's object graph: a session file normally *renews* its session
    (kills and recreates it), after which libtmux's cached ``$id`` and window
    list are stale and raise "list-windows: can't find session: $N". Asking
    tmux for the current state each time is both correct and cheap.
    """
    session_name = session.session_name

    try:
        window_name = compat.window_state(session_name)[1]
    except compat.CompatError as exc:
        raise compat.CompatError(
            f"session {session_name!r} is not ready to be filled ({exc}). A "
            f"session file must create its session (renew_session) and its "
            f"window (new_window) before calling panes_from_list()."
        ) from exc

    def window_state():
        """(window_id, window_name, active_pane_id) for the window we fill.

        Re-read from tmux on every step for two reasons: the window id is
        what every call below targets (so keys cannot land in a window
        another client switched to), and a session file may renew its session
        between calls. A missing session is reported as such, because the
        usual cause is the panes' own programs exiting -- a window with no
        panes is destroyed, and a session with no windows dies with it.
        """
        try:
            return compat.window_state(session_name, window_name)
        except compat.CompatError as exc:
            raise compat.CompatError(
                f"session {session_name!r} disappeared while filling window "
                f"{window_name!r}: {exc}\n"
                f"That normally means every pane in the window ran something "
                f"that exited (the window dies with its last pane). Check the "
                f"last commands sent to {window_name!r}."
            ) from exc

    # Split first, then fill. Doing it the other way round means a pane whose
    # script ends in `exit` (which is normal for a demo: run a tool, quit it)
    # destroys its window before the next split happens, taking the session
    # with it. Creating every pane up front makes the window's existence
    # independent of what the first pane's content does.
    total = len(keys_to_send_list)
    for index in range(1, total):
        compat.split_pane(None, session_name,
                          attach=True,
                          start_directory=start_directory,
                          window_id=window_state()[0])
        compat.select_layout_for(None, session_name, 'tiled',
                                 window_id=window_state()[0])

    # Fill them in the order they were created: pane 0 (the original) first,
    # then the splits in order.
    pane_ids = compat.pane_ids_of_window(window_state()[0])
    for index, i in enumerate(keys_to_send_list):
        if all_unchecked:
            keys = f"# skip check comming = 99999 #all unchecked \n{i}"
        else:
            keys = i
        try:
            pane_id = pane_ids[index]
        except IndexError:
            raise compat.CompatError(
                f"window {window_name!r} has fewer panes than the "
                f"{total} entries passed to panes_from_list(); a pane "
                f"probably exited early")
        try:
            send_keys_to_pane(
                compat.pane_by_id(pane_id),
                keys,
                time_out_unchecked=0,
                send_enter_last_row=send_enter,
                debugging=debugging,
            )
        except (compat.CompatError, KeyError) as exc:
            # The pane went away mid-send: its content ran something that
            # exited, and the window (and maybe the session) went with it.
            # Other spawn_* functions are unaffected, so report and stop
            # filling this window instead of aborting the whole run.
            print(f"{{panes_from_list}} pane {pane_id} of window "
                  f"{window_name!r} disappeared: {exc}")
            return
        if not compat.get_session(compat.connect(), session_name):
            print(f"{{panes_from_list}} session {session_name!r} exited after "
                  f"filling pane {pane_id} (its content ended with `exit`)")
            return
    compat.select_layout_for(None, session_name, 'tiled',
                             window_id=window_state()[0])


def _pane_target(pane):
    """The most specific target string tmux will accept for this pane.

    A pane id (%N) is unique across the whole server and survives renames,
    which is exactly what a remote or sudo target needs: session *names* are
    not unique across servers and "the session's active pane" is whatever was
    active last, not the pane the caller is holding.
    """
    pane_id = getattr(pane, "pane_id", None)
    if pane_id:
        return pane_id
    return f"{pane.session.name}:{pane.window_index}.{pane.pane_index}"


def pane_capture(pane,
                 size=15,
                 old_method=False,
                 debugging=False,
                 raw=False
                 ):
    """Visible (or scrollback) text of a pane, as a list of lines.

    Goes through termstate's tmux source rather than `tmux` on $PATH, so this
    works unchanged against a remote host or a sudo server.
    """
    res = []
    if old_method:
        res = pane.cmd('capture-pane', '-p',
                       '-S',  "-" + str(size)).stdout
    else:
        target = _pane_target(pane)
        len_cmd = ["capture-pane", "-t", target, "-p", "-S", "-" + str(size + 2)]
        while res == []:
            rc, out, _ = termstate.tmux_source().run(
                "capture-pane", "-t", target, "-p", "-S", "-" + str(size))
            res = out[:-1].split('\n') if (rc == 0 and out) else []
    if raw:
        return res
    rc, out, _ = termstate.tmux_source().run(*len_cmd)
    len_ = out[:-1].split('\n') if rc == 0 and out else []
    if len(res) == len(len_):
        for counter, i in enumerate(res[::-1]):
            if i != '':
                break
        if counter != 0:
            reshape_to_no_spaces_at_back = (counter * -1)
            if debugging:
                dbg = f"res before reshap: {res}"
                print(dbg)
            res = res[:reshape_to_no_spaces_at_back]
            if debugging:
                dbg = f"len(res): {len(res)}, len(len_): {len(len_)}, res: {res}, counter: {counter}"
                print(dbg)

    return res


def send_file_to_pane(pane, file_name, skip_checking=False):
    if skip_checking:
        prefix_file = '# skip check comming = 99999\n'
    else:
        prefix_file = ""
    file_content = prefix_file + \
        get_file_content(get_dir_session_files(args.scripts)[file_name])
    send_keys_to_pane(pane, file_content)


def get_attached_pane(server, session_name="main"):
    return compat.active_pane(compat.require_session(server, session_name))


def _as_pane(pane):
    """Return a live libtmux Pane for a pane object or a `%N` id string.

    Callers often only have the id: a session file's libtmux handles go stale
    once `renew_session` recreates the session, so the id is the durable handle.
    Both `at_end` and `wait_pane_idle` document accepting either; resolving here
    keeps that promise (a str has no `capture_pane`, which is what crashed).
    """
    if hasattr(pane, "pane_id"):
        return pane
    return compat.pane_by_id(str(pane))


def at_end(pane, time_out=1, debugging=False,
           send_enter_to_check_if_interpreter=True,
           require_shell=False,
           probe=False,
           expect_host=None):
    """True when the program in `pane` is blocked waiting for terminal input.

    Previous implementation typed 52 characters of junk into the pane, erased
    them, sent C-m, and compared the screen against a global list of
    remembered "interpreter" strings. That failed on the cases that matter
    (silent readers like smbclient/mysql print nothing to match; remote shells
    have arbitrary prompts; msfconsole is never "the shell") and it mutated
    the pane it was measuring.

    This asks the kernel instead: find the process that owns the pane's tty,
    then check whether it is blocked in a read. No keystrokes are sent.

    The old version of this function answered the question by typing junk into
    the pane. That was rightly removed, because it mutates what it measures. So
    for an ordinary shell pane the `/proc` check is the whole answer.

    It is NOT sufficient for a pane that hosts another terminal (QEMU's serial
    console, screen, minicom): there the foreground process is blocked on the
    tty for its entire lifetime, so process state is always "ready". For those,
    pass `probe=True` to fall back to the only signal that still means
    something there: send a bare Enter and require the pane to look the same
    afterwards (a real prompt redraws identically; a booting guest, a login
    prompt, or a running command does not).

    `require_shell` additionally refuses a *nested* prompt (a REPL, or a
    hypervisor monitor like QEMU's). Those accept input but reject a shell
    command with "unknown command", so sending into one looks like a silent
    failure. Default False keeps the old behaviour for callers that do mean to
    drive the nested prompt.

    `expect_host` requires the prompt to name that host, for a pane that hosts
    a whole machine: without it the shell that *launched* the guest (e.g.
    "[nix-shell:~/repo]$") is indistinguishable from the guest's own prompt, and
    commands silently run on the wrong machine.

    The same hazard exists one level up with `--target HOST`: the pane may
    still be showing *our* shell while the ssh connection is being set up. The
    process-state check covers that (an `ssh` client is not blocked reading
    the tty), so `expect_host` stays opt-in here rather than being forced on
    every pane of a remote target.
    """
    # Accept a pane object OR a pane id string (`%N`). Everything below needs a
    # real pane: `_stable_prompt`/`capture_pane` call `pane.capture_pane()`, which
    # a str does not have -- that AttributeError is what the "pane or id" docstring
    # promised but did not deliver. Resolve once, here.
    pane = _as_pane(pane)
    target = pane.pane_id

    # For a pane that hosts another terminal the process state cannot answer
    # anything, so ask the redraw question first and hand the answer to
    # termstate, which uses it both to decide readiness and to *learn* the
    # prompt it is looking at (see termstate.pane_state's `stable`).
    # Ask it only when it could matter: a plain shell pane is already answered
    # by process state, and the probe sends a keystroke.
    hosts_terminal = termstate.is_terminal_host(target)
    stable = None
    if probe or (hosts_terminal and send_enter_to_check_if_interpreter):
        stable = _stable_prompt(pane, debugging=debugging)

    state = termstate.pane_state(target, expect_host=expect_host,
                                 stable=stable)
    if debugging:
        print(f"{{at_end}} {termstate.describe(target)}")
    # ready = the tty owner wants input. safe_to_send additionally keeps a
    # command line out of a password / pager / yes-no prompt.
    if not (state.ready and state.safe_to_send):
        return False
    if require_shell and state.prompt is not None and state.prompt.is_nested_shell():
        if debugging:
            print(f"{{at_end}} refusing nested prompt {state.prompt}")
        return False
    if probe:
        return bool(stable)
    return True


# Asynchronous console output is identified by its timestamp prefix, not by
# the name of the program that wrote it (see prompts.CONSOLE_NOISE).
_CONSOLE_JUNK = prompts.CONSOLE_NOISE

# A login prompt is stable text that is never a shell.
_LOGIN_PROMPT = re.compile(r"\blogin:(\s|$)")

# Lines that are *output*, never a shell waiting for input. They matter because
# the probe below has no echo to go on: it sends an empty Enter, so the screen
# is identical whether the line came from a prompt or from a program that is
# still working. Measured 2026-11-11: a `nixos-shell` boot was reported READY
# while `nix build` was still printing `[17/21 built, 3 copied (13.7 MiB) ...]`,
# which no redraw test can distinguish from a prompt -- so the acceptance probe
# typed into a build and ran its commands on the host shell instead of the
# guest.
_NOT_A_SHELL_LINE = (
    # Nix's progress bar. Two shapes, both live: `[17/21 built, 3 copied ...]`
    # (currently building) and `[1/11/21 built, 3 copied ...]` (built, copied
    # and to-download totals).
    re.compile(r"^\[\s*\d+/\d+(?:/\d+)? built"),
    # Nix/`nix-build` log shapes: "building '...drv'...", "copying path ...".
    re.compile(r"^(?:building|copying|fetching|unpacking|installing|evaluating)\b"),
    # A line that ends in an ellipsis is describing continuation, not asking.
    re.compile(r"(\.\.\.|…)$"),
)


def _screen_signature(pane):
    """The pane's *visible* content: junk stripped, trailing blanks dropped.

    Only the visible screen is considered. Reading scrollback would reach back
    into history -- an earlier monitor prompt or a finished command -- and make
    the pane look like something it no longer is.

    Timestamped console output is removed rather than compared, because it
    arrives asynchronously and would make any two samples differ.
    """
    lines = []
    for line in compat.capture_pane(pane):
        # A line carrying console junk is dropped whole: blanking just the
        # matched token leaves fragments (" : y") that still differ between
        # samples, which is exactly what this comparison must not see.
        if _CONSOLE_JUNK.search(line):
            continue
        lines.append(line.rstrip())
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _stable_prompt(pane, debugging=False):
    """True when a bare Enter leaves the pane looking the same.

    This is the check that works for a pane hosting another terminal, where
    process state cannot help. A program at a prompt redraws that prompt
    identically on an empty Enter; a booting guest, a login prompt, or a
    command still producing output does not.

    An unknown prompt is exactly the case this has to handle (a guest's PS1, a
    themed shell), so a strict `prompts.match_line` gate would make the check
    useless for precisely the panes that need it. But "the last line repeats"
    alone is not enough either: a login banner is perfectly stable, so it is
    accepted as a prompt and a caller then types a command into a login prompt.
    Measured 2026-11-10: `isp-neon login: root (automatic login)` was reported
    READY.

    The rule is therefore: the line must be stable AND must not be a line the
    prompt table positively identifies as NOT a shell. A line the table knows is
    a login prompt, a password prompt or a nested REPL is rejected; anything it
    does not know is still accepted, which keeps unknown prompts working.
    """
    def prompt_line():
        """The live prompt, with console junk cut off wherever it starts.

        The junk is frequently written *onto* the prompt line rather than after
        it, so the tail is truncated at the first junk match rather than the
        whole line being discarded -- otherwise a busy console looks like it
        has no prompt at all.
        """
        for line in reversed(compat.capture_pane(pane)):
            m = _CONSOLE_JUNK.search(line)
            if m is not None:
                line = line[: m.start()]
            line = line.rstrip()
            if line.strip():
                return line
        return ""

    def is_not_a_shell(line):
        """True when the prompt table says this line is definitely not a shell."""
        try:
            import prompts as _prompts
        except Exception:
            return False
        # Login banners are the case that matters: they are stable text and are
        # never a shell, so accepting them sends a command to a login prompt.
        if _LOGIN_PROMPT.search(line):
            return True
        if any(pattern.search(line) for pattern in _NOT_A_SHELL_LINE):
            return True
        m = _prompts.match_line(line)
        if m is None:
            return False
        return not m.safe_to_send or m.is_nested_shell()

    before = prompt_line()
    if not before:
        if debugging:
            print("{at_end/probe} nothing on screen to settle")
        return False
    if is_not_a_shell(before):
        if debugging:
            print(f"{{at_end/probe}} not a shell: {before!r}")
        return False

    compat.send_keys(pane, "")
    compat.send_keys(pane, "C-m")

    # A busy console may still be logging, in which case the *exact* last line
    # never repeats. What must hold is that the last line came back and did not
    # turn into a different piece of text: a guest that is booting or running a
    # command loses it or replaces it, so this is still a real check.
    deadline = time.time() + 2.0
    while time.time() < deadline:
        time.sleep(0.1)
        after = prompt_line()
        if not after:
            continue
        if after == before:
            if is_not_a_shell(after):
                if debugging:
                    print(f"{{at_end/probe}} stable but not a shell: {after!r}")
                return False
            if debugging:
                print(f"{{at_end/probe}} stable line: {after!r}")
            return True
        # Console noise written over the prompt: compare up to the junk.
        before_head = before[: len(after)] if _CONSOLE_JUNK.search(before) else before
        if _CONSOLE_JUNK.search(before) and after == before_head:
            if debugging:
                print(f"{{at_end/probe}} stable prompt under noise: {after!r}")
            return True
    if debugging:
        print(f"{{at_end/probe}} did not settle (was {before!r})")
    return False


class PaneBusy(Exception):
    """The pane never reached a terminal state inside the caller's budget."""


def _pane_output(pane):
    """Output of the job that just finished: the screen minus what was there.

    `baseline` is the pane's screen captured when the wait started. Everything
    up to and including the last line of that baseline is prior content (old
    output, the previous prompt); the command's echo and its output are what
    appeared after it. Framing (prompts, prompt chrome, wrapped prompt
    fragments) is then dropped line by line, so an empty result means the
    command printed nothing.
    """
    lines = [ln.rstrip() for ln in compat.capture_pane(pane, start="-40")]
    try:
        import prompts as _prompts
    except Exception:
        _prompts = None

    def is_framing(ln):
        text = ln.strip()
        if not text:
            return True
        if text[0] in "\u2500\u250c\u2514\u2502\u251c\u250f\u2570\u256d\u2571\u2572\u2550":
            return True
        if text.endswith("]") and len(text) <= 24 and any(c.isdigit() for c in text):
            return True
        if "\u2514\u2500" in text or "\u250c\u2500" in text:
            return True
        if _prompts is not None:
            stripped = _prompts.strip_console_noise(text)
            if _prompts.match_line(stripped) is not None:
                return True
        return False

    i = len(lines) - 1
    while i >= 0 and is_framing(lines[i]):
        i -= 1
    end_nonframing = i
    block = []
    while i >= 0 and not is_framing(lines[i]):
        block.append(lines[i])
        i -= 1
    block.reverse()

    return "\n".join(block).strip()


def wait_pane_idle(pane, timeout=3600.0, poll=0.25, debugging=False,
                   expect_host=None, grace=2.0):
    """Block until the pane's foreground job finishes; return the exit line.

    Callers kept writing their own `while ... sleep` loops, and they failed the
    same ways each time: polling a marker that can never arrive, no failure
    condition for a launcher that died, and nothing reported until the loop
    ended. That is why an interrupted `nixos-shell` looked like a 25-minute
    hang and a finished build was still being waited on.

    This waits on the *process*, not on a string, and it is deliberately built
    on `at_end` rather than on a bare `termstate.pane_state` call: `at_end` is
    the one place that knows a pane hosting another terminal (QEMU's console,
    `screen`, `minicom`) is *always* blocked on its tty, so process state alone
    would call a booting guest "idle" -- the exact failure the redraw probe
    exists to prevent. For a terminal host the probe is required, so it is
    always requested here.

    Returns the job's output: the screen block between the echoed command and
    the prompt it returned to, with prompt chrome removed. It used to return the
    prompt line itself (measured 2026-11-12: `'\u2514\u2500[%]'`), which could
    not tell "printed nothing" from "printed something".

    One ambiguity remains by construction: a command that prints *nothing*
    leaves only its echoed line, which is indistinguishable from one line of
    output without knowing what was typed. Use `wait_pane_output(pane, cmd)`
    when you control the command and need an exact answer. Raises `PaneBusy`
    when the budget runs out.

    A launcher that exited is a finish, not a hang: `termstate.launcher_exited`
    says which, and the caller can tell the cases apart from the returned text.

    A pane that is *already* idle when this is called has not necessarily
    finished anything: immediately after the pane is created the shell is idle,
    and returning on that first sample reports "finished" for a command that has
    not started (measured 2026-11-12: the tail was the typed text still sitting
    at the prompt, and the command only ran after an extra Enter). So an idle
    sample is only accepted once the pane has been seen busy, unless
    `grace` seconds pass with it never becoming busy -- which keeps commands
    that finish instantly from wedging the caller.
    """
    pane = _as_pane(pane)
    target = pane.pane_id
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    seen_busy = False
    while time.monotonic() < deadline:
        # A terminal host can only be judged by its screen, so the probe is
        # mandatory there; elsewhere process state is the whole answer and the
        # probe would needlessly type an empty Enter into an ordinary shell.
        probe = termstate.is_terminal_host(target)
        ready = at_end(pane, probe=probe, expect_host=expect_host,
                       debugging=debugging)
        if not ready:
            seen_busy = True
        elif seen_busy or (time.monotonic() - start) >= grace:
            return _pane_output(pane)
        if termstate.launcher_exited(target):
            tail = [ln for ln in compat.capture_pane(pane, start="-24")
                    if ln.strip()]
            return tail[-1].rstrip() if tail else ""
        time.sleep(poll)
    raise PaneBusy(
        f"pane {target} was still busy after {timeout:.0f}s: "
        f"{termstate.describe(target)}"
    )


def wait_pane_output(pane, inner_cmd, timeout=120, **kwargs):
    """Run `inner_cmd` in `pane` and return its output, verified.

    `wait_pane_idle` answers "has the job in this pane finished" and returns the
    output block it can see. That is ambiguous for a command that prints
    nothing: the echoed command line is indistinguishable from one line of
    output without knowing what was typed (measured 2026-11-12). This is the
    unambiguous alternative: it types the command with a marker-framed pipe
    (`pane_stream`) so "="" (printed nothing) and "=echo text" never collide.

    Use `wait_pane_idle` when the job was started by someone else (a `spawn_*`
    or an agent) and you only need to block; use this when you control the
    command and want its result.
    """
    pane = _as_pane(pane)
    return pane_stream(pane, inner_cmd, **kwargs)


def checked_cmd(pane,
                row_to_send,
                last_row_send,
                time_out=1,
                debugging=False,
                complete_timeout=120):
    """Wait until the pane is at a prompt, send the row, then wait for it to finish.

    The wait *after* sending is the important half and it used to be a single
    fixed sleep. That returns before a long command has finished, so the caller
    reads whatever happens to be on screen: measured 2026-11-10, a
    `systemctl restart pppd; sleep 20; ip show ppp0` returned immediately with
    no output at all, and the follow-up read showed the *previous* command's
    result. Anything that took longer than `time_out` looked like it had
    produced nothing.

    Completion is decided by the prompt returning (through `at_end`), not by a
    timer, with `complete_timeout` as a bound so a hung command still surfaces.
    """
    while 1:
        try:
            if (len(last_row_send) > 5) and last_row_send == "".join(pane_capture(pane))[len(last_row_send):]:
                print("{checked_cmd}, last command still in last row")
                continue
        except KeyError:
            if debugging:
                print('{checked_cmd}, KEY ERROR, checked_cmd')
        if at_end(pane, debugging=debugging):
            if debugging:
                print('{checked_cmd} breaked while at_end loop')
            break
        if last_row_send is None:
            break

        if debugging:
            print('{checked_cmd} sleeping at_end = False')
        time.sleep(time_out)
    # Discard any half-typed line first. A `spawn_*` that seeds the pane with a
    # command returns after a fixed send delay, without confirming the shell
    # consumed the trailing Enter; typing now concatenates onto it
    # (`truecd /repo && ...` -> `command not found: truecd`) while the end
    # marker still prints, so the caller gets exit=127 and no explanation
    # (BUG-checked-cmd-concatenates-onto-the-previous-command, measured
    # 2026-11-12). C-u clears whatever is on the line; it is harmless when empty.
    compat.send_keys(pane, "C-u")
    compat.send_keys(pane, row_to_send)
    compat.send_keys(pane, "C-m")

    # Wait for the command to complete: the prompt must go away and come back.
    #
    # Testing "is the shell ready" alone is not enough -- it is ready the instant
    # the line is sent, before the command has run at all, which is how a
    # completion check can pass immediately. So the prompt must first be observed
    # GONE (the shell is executing), then observed again. A command that prints
    # nothing still occupies the shell, so the gap is real rather than inferred
    # from output.
    # Completion is decided by a MARKER the command prints when it is done.
    #
    # No prompt heuristic can work here. In a pane that hosts a terminal (QEMU's
    # serial console, screen, minicom) the foreground process is blocked on the
    # tty for its whole lifetime, so /proc says READY during a boot, at a login
    # prompt and while a command runs; measured 2026-11-10, `sleep 6` was
    # reported READY for five consecutive samples. The screen is no better: a
    # command that has not printed yet leaves the old prompt as the last line,
    # so "did the prompt come back" is indistinguishable from "it never left".
    # There is also no host-side process to inspect, because the command runs
    # inside the guest.
    #
    # A marker appended to the command is the only signal that means exactly one
    # thing: the shell reached the end of that command. `wait_untill_msg` ignores
    # the terminal's echo of the command line, so this cannot be satisfied by the
    # text we typed ourselves.
    marker = f"__CC_{os.getpid()}_{int(time.time() * 1000)}__"
    compat.send_keys(pane, f"echo {marker}_B; {row_to_send}; echo {marker}_E")
    compat.send_keys(pane, "C-m")
    if wait_untill_msg(pane, f"{marker}_E", timeout=complete_timeout):
        if debugging:
            print('{checked_cmd} completed (end marker seen)')
        return
    print(f"{{checked_cmd}} did not complete within {complete_timeout}s: "
          f"{row_to_send!r}", file=sys.stderr)


def interactive_dashboard(session_functions, debugging):
    # `-i` is a real REPL: it reads a menu choice from stdin. Piping a command
    # list into it used to crash with an EOFError from `input()`; refuse with a
    # clear message instead, and point at the non-interactive path.
    if not sys.stdin.isatty():
        print(
            "dashboard: --interactive needs a TTY (it reads menu choices from "
            "stdin). Drop -i to spawn every spawn_* and exit.",
            file=sys.stderr,
        )
        return 2
    while 1:
        global all_files
        all_files = get_dir_session_files(args.scripts)
        # print(session_functions)
        for counter, i in enumerate(session_functions):
            print(counter, "=", i)
        print("a = spawn all")
        print("exit/quit = quit app")
        id = input('id to spawn or name to spawn: ')
        if id == "":
            continue
        if id == "quit" or id == "exit":
            exit()
            break
        if not(debugging):
            run(['clear'], check=False, capture=False)
        print('id to spawn or name to spawn: ' + id)
        if "all" == id or "a" == id:
            for i in session_functions:
                start = f"{i}()"
                print(f"interactive_dashboard: start {start}")
                exec(start)

        call_direct = ""
        list_of_spawn = ["_".join(i.split('_')[1:])
                         for i in session_functions]
        for counter, spawn in enumerate(list_of_spawn):
            if id in spawn:
                call_direct = session_functions[counter]
                break
        if call_direct == "":
            # Bare number selects by index; anything else is a typo. The
            # original called int(id) unconditionally here, which raised
            # ValueError for out-of-range or non-numeric input.
            if not id.isdigit() or int(id) >= len(session_functions):
                print(f"no session matches {id!r}; try a number 0-"
                      f"{len(session_functions) - 1} or a name")
                continue
            call_direct = session_functions[int(id)]
        exec_function = f"{call_direct}()"
        print(exec_function)
        exec(exec_function)


def find_str_in_history(string_to_find, pane, steps=50):
    found = False
    size_m = -1
    while not(found):
        pane_cap = "\n".join(pane_capture(pane, size_m))
        if string_to_find in pane_cap:
            found = not(found)
        else:
            size_m += steps
    pane_cap = pane_cap.split('\n')
    pane_cap.reverse()
    for counter, row in enumerate(pane_cap):
        print(counter, row)
        if string_to_find in row:
            result_counter = len(pane_cap) - counter
            break
    return result_counter


# unused in script but easy for cli
def s_all(respawn_all=True):
    for session_function in session_functions:
        name = f"{session_function.split('_')[-1]}"
        func = f"{session_function}()"
        if respawn_all:
            # `spawn_<name>()` creates the session itself (it calls
            # renew_session). Do NOT pre-create here: renew_session(...)
            # with keep_session=True returns None on a fresh target, so the
            # old `compat.active_pane(renew_session(name, keep_session=True))`
            # crashed before the session file had a chance to spawn.
            print(f'Starting {func}')
            exec(func) in globals(), locals()
            session = compat.get_session(server, name)
            if session is None:
                print(f"dashboard: {func} did not create session {name!r}",
                      file=sys.stderr)
                continue
            name_pane = compat.active_pane(session)
        else:
            # Probe with get_session (quiet) rather than require_session, which
            # raises CompatError -- the old `except AttributeError` never caught
            # it, so a fresh target printed `dashboard: no tmux session named
            # '<x>'` and aborted before the spawn branch could run.
            if compat.get_session(server, name) is not None:
                print(f"Trying to get active_pane of {name}")
                name_pane = compat.active_pane(
                    compat.require_session(server, name))
                pane_name_as_var = f'global {name}_pane; {name}_pane = name_pane'
                exec(pane_name_as_var) in globals(), locals()
                continue
            print(f'Starting {func} because its not spawned yet')
            exec(func) in globals(), locals()
            name_pane = compat.active_pane(renew_session(
                name,
                keep_session=True
            ))
        exec(f'{name}_pane = name_pane') in globals(), locals()


def parse_args():
    default_interpreters = [
        '>',
        r'PS C:\Windows\system32>',
        r'C:\Windows\system32',
        'meterpreter >',
        'mimikatz #',
        '└─#',
        '└─$',
        '▶'
    ]
    parser = argparse.ArgumentParser(
        description="Scripted multi-pane tmux orchestration.",
        epilog="""
Targets (--target), so the same session files work anywhere:

  local                 this machine, your tmux      (the default)
  local:sudo            `sudo tmux` here  -> panes are root's
  local:sudo-login      your tmux here, panes run `sudo -i`
  DEVBOX                a host over ssh: needs `ssh DEVBOX true` to work
                        without a prompt (key auth; ~/.ssh/config applies)
  DEVBOX:sudo           `sudo tmux` on DEVBOX (its root pane)
  DEVBOX:sudo-login     your tmux on DEVBOX, panes run `sudo -i`
  HOST,sock=NAME        `tmux -L NAME` on HOST

Panes are created in whatever session your session file names, so the
remote host keeps its normal layout. Spawn-all attaches with
`tmux attach -t spawn-all`, which exists on every target.

Pane readiness is decided from /proc, which must be readable on the machine
(or user) that owns the panes. For --target HOST or a :sudo target that
means one shell round-trip per rescan; if it fails, detection degrades to
the on-screen prompt and says so.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("DASHBOARD_TARGET", "local"),
        type=str,
        help="where the tmux server lives: local (default), HOST, HOST:sudo, "
             "local:sudo, HOST:sudo-login, HOST,sock=NAME "
             "(default: $DASHBOARD_TARGET or 'local')",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify --target (tmux reachable, /proc readable, host name) "
             "and exit; useful before pointing a session file at a new host",
    )
    parser.add_argument(
        "--session-file",
        help="configuration file, check the scripts directory if you dont know how to make one.",
        default="scripts/1_session.py",
        type=str
    )
    parser.add_argument(
        "--additional-interpreters",
        nargs='+',
        action='append',
        type=str,
        help="List of interpreters"
    )
    var = False
    parser.add_argument(
        '-i',
        '--interactive',
        help="""is interactive shell, 
if used, 
    it will spawn an interactive shell. 
if not used, 
    all sessions will be spawned.
""",
        action='store_const',
        default=var,
        const=not(var)
    )
    parser.add_argument(
        'scripts',
        help="location of the script called inside the session.py",
        type=str
    )
    args = parser.parse_args()
    args.interpreters = default_interpreters
    if isinstance(args.additional_interpreters, list):
        for i in args.additional_interpreters:
            if i == '':
                continue
            [args.interpreters.append(j) for j in i]
    return args


def main():
    global interpreters, server, all_files, args
    sys.setrecursionlimit(15000)

    # Refuse root before touching tmux: a tmux server is per-user, so a
    # root-run dashboard spawns into a different server and leaves root-owned
    # files behind. See AGENTS.md, "Run as a normal user".
    try:
        compat.assert_not_root()
        compat.assert_env_sane()
        compat.check_libtmux_version()
    except compat.CompatError as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        return 2

    args = parse_args()
    interpreters = args.interpreters
    try:
        server = connect_server(args.target)
    except (compat.CompatError, remote.RemoteError) as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        return 2
    location = args.session_file

    if args.check:
        return preflight(server, globals().get("dashboard_target"))

    # The session file is exec'd into module globals (not main()'s locals) so
    # that (a) spawn_* functions defined there become module-level names the
    # spawner can find, and (b) `dir()` below sees them. exec'ing into locals
    # would hide them from both.
    user_functionality = get_file_content(location).\
        rsplit('if __name__ == "__main__":', -1)[0]
    exec(compile(user_functionality, location, "exec"), globals())

    # dir(globals()) would list dict's own attributes; the spawn_* names live
    # in the dict itself, so pass the mapping's keys.
    session_functions = natural_sort(
        list_potentional_sessions(globals())
    )
    # s_all() and the post-run pane binding below read these from module
    # globals, and the interactive dashboard re-reads all_files each pass.
    globals()["session_functions"] = session_functions
    all_files = get_dir_session_files(args.scripts)

    # One name per spawn_* function, so a session file may spawn several
    # windows without a second spawn_* being invented for them.
    if args.interactive:
        rc = interactive_dashboard(
            session_functions,
            debugging=True
        )
        if rc:
            return rc
    else:
        # Non-interactive mode is the documented unattended path (no REPL): it
        # must SPAWN every `spawn_*` in the session file, not attach to one. The
        # old `s_all(respawn_all=False)` took the attach branch, so on a fresh
        # target it printed `no tmux session named '<x>'`, created nothing, and
        # still exited 0 -- a silently empty success (BUG-noninteractive-...).
        s_all(respawn_all=True)

    missing = []
    for session_function in session_functions:
        name = f"{session_function.split('_')[-1]}"
        named_pane = name + "_pane"
        session = compat.get_session(server, name)
        if session is None:
            # A pane whose shell exits (e.g. a non-interactive command that
            # returns) lets tmux reap the session. Report it instead of
            # silently continuing with exit 0.
            missing.append(name)
            continue
        globals()[named_pane] = compat.active_pane(session)

    if missing:
        print(
            "dashboard: session(s) not present after spawn: "
            + ", ".join(repr(n) for n in missing)
            + ". A pane's shell likely exited; panes must keep an interactive "
            "shell alive (or set remain-on-exit) for the session to survive.",
            file=sys.stderr,
        )
        return 1

    # Leftover REPL for convenience: `python3 -i main_tdashboard.py ...`
    # exposes the pane_<name> variables bound above. Use plain `-i`, not
    # ipython: the original `#!/usr/bin/ipython3` shebang does not exist on
    # most systems and added a hard dependency for no gain.
    return 0


def connect_server(target_spec="local"):
    """Point the dashboard at `target_spec` and return its tmux Server.

    This is the one place that decides *which* tmux server the whole run
    talks to, and it decides it three times over, deliberately:

    * `compat.set_server_target` -> every libtmux call (sessions, windows,
      panes, splits);
    * `termstate.set_tmux_source` -> capture-pane and display-message, used
      for prompt detection and pane text;
    * `termstate.set_proc_source`  -> the /proc that decides readiness, which
      for a remote host or a sudo server is *not* ours.

    A shim on disk bridges libtmux to a remote or sudo `tmux` (see
    remote.make_tmux_shim). For the default target none of this is injected
    and the dashboard behaves exactly as before.
    """
    try:
        target = remote.parse_spec(target_spec)
    except remote.RemoteError as exc:
        raise compat.CompatError(f"bad --target {target_spec!r}: {exc}")

    if target.transport == "local" and not target.sudo:
        compat.set_server_target(socket_name=target.socket)
        termstate.set_tmux_source(termstate.TmuxSource())
        termstate.set_proc_source(termstate.LocalProc())
        server = compat.connect()
        expect_host = remote.host_identity()
    else:
        if not shutil.which("ssh") and target.transport == "ssh":
            raise compat.CompatError(
                "ssh is not installed, so --target "
                f"{target.name!r} cannot be reached")
        if target.transport == "ssh" and target.sudo and \
                not _ssh_noninteractive_ok(target.host):
            raise compat.CompatError(
                f"--target {target.name!r}: `ssh {target.host}` does not work "
                f"without a prompt. A dashboard cannot answer a password or "
                f"passphrase prompt; set up a key (or a warm ControlMaster) "
                f"first, and verify with:  ssh {target.host} true")
        tmpdir = tempfile.mkdtemp(prefix="tmux-dashboard-")
        session = remote.install(target, tmpdir)
        try:
            session.check()
        except remote.RemoteError as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise compat.CompatError(str(exc)) from exc
        server = compat.connect()
        expect_host = remote.remote_host_identity(target, session)

    globals()["dashboard_target"] = target
    globals()["target_host"] = expect_host
    if target.transport == "ssh":
        print(f"dashboard: target {target.describe()}  (host {expect_host})")
    return server


def preflight(server, target):
    """Report what a --target can actually do, and return an exit code.

    The question this answers is the one that is expensive to get wrong: can
    this dashboard *detect readiness* on that target, or will it only be able
    to type? Detection needs /proc on the machine that owns the panes, so a
    remote host gets one probe, and a sudo target gets the same probe under
    sudo. Everything is reported, nothing is guessed.
    """
    print(f"target: {target.describe() if target else 'local'}")
    try:
        sessions = compat.list_session_names(server)
    except Exception as exc:
        print(f"  tmux:  FAILED ({exc})")
        return 2
    print(f"  tmux:  ok ({len(sessions)} session(s)"
          + (f": {', '.join(sessions[:8])}" if sessions else "") + ")")

    proc = termstate.proc_source()
    name = type(proc).__name__
    if isinstance(proc, termstate.LocalProc):
        print(f"  /proc: ok ({name}: this machine, this user)")
        print("  host:  " + remote.host_identity())
        return 0

    # Remote or sudo: prove the probe works by classifying a real process on
    # the far side. Our own pid is wrong -- it does not exist there.
    session = remote.TargetSession(target)
    try:
        src = termstate.RemoteProc(session)
        # A pid that is guaranteed to exist on the far side *and* to persist:
        # pid 1. Reading its stat is exactly the permission that decides
        # whether readiness detection can work at all.
        pid = 1
        own = src.stat(pid)
    except Exception as exc:
        print(f"  /proc: FAILED ({exc})")
        return 2
    if own is None:
        print(f"  /proc: FAILED ({src.last_error or 'probe returned nothing'})")
        print("         spawning will work, but readiness will fall back to "
              "screen matching")
        return 1
    print(f"  /proc: ok ({name}: pid {pid} -> {own['comm']}, "
          f"wchan available)")
    print("  host:  " + remote.remote_host_identity(target, session))
    return 0


def _ssh_noninteractive_ok(host, timeout=10):
    """Would `ssh host true` succeed without asking us anything?"""
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=" +
             str(timeout), host, "true"],
            capture_output=True, text=True, timeout=timeout + 5)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (compat.CompatError, remote.RemoteError) as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        sys.exit(2)
