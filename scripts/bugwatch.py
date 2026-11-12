#!/usr/bin/env python3
"""Watch a directory for BUG*.md events (create/append/rewrite/delete).

Linux inotify via ctypes; blocks in select() -- no sleep, no polling, no tmux.

One logical change per file, printed once:

  NEW        a BUG*.md that did not exist before (even 0 bytes)
  APPEND     bytes added on top of unchanged content (prints the delta)
  REWRITE    content replaced/changed but not a pure append (prints it all)
  DELETE     the file disappeared

Raw inotify emits several events per save (CREATE, MODIFY*n, CLOSE_WRITE), so
the whole queue is drained before acting and each file is flushed once, at the
earliest deadline seen for it. State is a single `known` map of name ->
(size, sha256); there is no sticky "deleted" set, so delete-then-recreate is
reported correctly.

Exit: this watcher is meant to be run by a caller that reads its output and acts
on it. `--once` makes it exit after the first reported event, so a caller can
"break out of the loop" instead of tailing forever.
"""
import ctypes
import ctypes.util
import hashlib
import os
import select
import struct
import sys
import time

DIRECTORY = "/home/deadbeef/github/dashboard"
ONCE = True  # exit on the first reported event by default
for arg in sys.argv[1:]:
    if arg == "--once":
        ONCE = True
    elif arg == "--follow":
        ONCE = False
    else:
        DIRECTORY = arg

QUIET = 0.15  # seconds a file must be unchanged before its event is flushed
              # (a coalescing timer, not a poll loop: select() blocks on it)

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
IN_NONBLOCK = 0x800
IN_MODIFY = 0x2
IN_CREATE = 0x100
IN_DELETE = 0x200
IN_MOVED_TO = 0x80
IN_CLOSE_WRITE = 0x8
MASK = IN_MODIFY | IN_CREATE | IN_DELETE | IN_MOVED_TO | IN_CLOSE_WRITE
E = 16  # sizeof(struct inotify_event)


def is_bug(name):
    return name.lower().startswith("bug") and name.endswith(".md")


def sha_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot():
    """name -> (size, sha256) for every BUG*.md currently present."""
    out = {}
    try:
        names = os.listdir(DIRECTORY)
    except OSError:
        return out
    for n in names:
        if not is_bug(n):
            continue
        path = os.path.join(DIRECTORY, n)
        try:
            out[n] = (os.path.getsize(path), sha_of(path))
        except OSError:
            pass
    return out


def main():
    fd = libc.inotify_init1(IN_NONBLOCK)
    if fd < 0:
        sys.exit(f"inotify_init1 failed: {os.strerror(ctypes.get_errno())}")
    if libc.inotify_add_watch(fd, DIRECTORY.encode(), MASK) < 0:
        sys.exit(f"inotify_add_watch({DIRECTORY}) failed: "
                 f"{os.strerror(ctypes.get_errno())}")

    known = snapshot()
    print(f"watching {DIRECTORY} for BUG*.md "
          f"(inotify, no sleep, no tmux{', --once' if ONCE else ''})",
          flush=True)
    for n in sorted(known):
        print(f"  present: {n} ({known[n][0]} bytes)", flush=True)

    pending = {}  # name -> earliest monotonic deadline to flush it

    while True:
        timeout = None
        if pending:
            timeout = max(0.0, min(pending.values()) - time.monotonic())
        readable, _, _ = select.select([fd], [], [], timeout)

        if readable:
            # Drain the whole queue so one save cannot be half-processed.
            while True:
                try:
                    data = os.read(fd, 65536)
                except BlockingIOError:
                    break
                except OSError:
                    break
                if not data:
                    break
                i = 0
                while i < len(data):
                    _wd, _mask, _cookie, ln = struct.unpack_from("iIII", data, i)
                    name = data[i + E:i + E + ln].split(b"\0", 1)[0].decode(
                        errors="replace")
                    i += E + ln
                    if name and is_bug(name):
                        # keep the earliest deadline for this file
                        pending.setdefault(name, time.monotonic() + QUIET)

        now = time.monotonic()
        fired = False
        for name in [n for n, due in pending.items() if due <= now]:
            del pending[name]
            path = os.path.join(DIRECTORY, name)
            try:
                sz = os.path.getsize(path)
                sha = sha_of(path)
            except OSError:
                if name in known:
                    print(f"\n=== DELETE: {name} ===", flush=True)
                    known.pop(name, None)
                    fired = True
                continue

            old = known.get(name)
            if old is None:
                print(f"\n=== NEW: {name} ({sz} bytes) ===", flush=True)
                if sz:
                    with open(path, errors="replace") as f:
                        print(f.read(), flush=True)
            else:
                old_sz, old_sha = old
                if sha == old_sha:
                    known[name] = (sz, sha)
                    continue
                appended = False
                if sz > old_sz:
                    # APPEND only when the original bytes are an exact prefix;
                    # a truncating rewrite can also grow the file.
                    try:
                        with open(path, "rb") as f:
                            prefix = f.read(old_sz)
                        appended = hashlib.sha256(prefix).hexdigest() == old_sha
                    except OSError:
                        appended = False
                if appended:
                    print(f"\n=== APPEND: {name} (+{sz - old_sz} bytes) ===",
                          flush=True)
                    with open(path, errors="replace") as f:
                        f.seek(old_sz)
                        print(f.read(), flush=True)
                else:
                    print(f"\n=== REWRITE: {name} (now {sz} bytes) ===",
                          flush=True)
                    if sz:
                        with open(path, errors="replace") as f:
                            print(f.read(), flush=True)
            known[name] = (sz, sha)
            fired = True

        if fired and ONCE:
            return 0


if __name__ == "__main__":
    sys.exit(main())
