#!/usr/bin/env python3
"""Watch a directory for BUG*.md events (create/append/delete).

Linux inotify via ctypes; blocks in select() -- no sleep, no polling, no tmux.

Per file it reports ONE line per settle:
  - NEW     a BUG*.md that did not exist before (even if empty)
  - APPEND  bytes added to a file already seen (prints only the new bytes)
  - DELETE  a file that disappeared

Settling: writers issue several raw events per save (CREATE, MODIFY xN,
CLOSE_WRITE). We coalesce them into one logical change per file and only print
once the file has been quiet for QUIET seconds (0.15) -- a timer, not a loop.
"""
import ctypes, ctypes.util, os, select, struct, sys, time

DIRECTORY = sys.argv[1] if len(sys.argv) > 1 else "/home/deadbeef/github/dashboard"
QUIET = 0.15

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
IN_NONBLOCK = 0x800
IN_MODIFY = 0x2
IN_CREATE = 0x100
IN_DELETE = 0x200
IN_MOVED_TO = 0x80
IN_CLOSE_WRITE = 0x8
MASK = IN_MODIFY | IN_CREATE | IN_DELETE | IN_MOVED_TO | IN_CLOSE_WRITE

fd = libc.inotify_init1(IN_NONBLOCK)
if fd < 0:
    sys.exit("inotify_init1 failed")
if libc.inotify_add_watch(fd, DIRECTORY.encode(), MASK) < 0:
    sys.exit(f"inotify_add_watch({DIRECTORY}) failed: {os.strerror(ctypes.get_errno())}")

E = 16
is_bug = lambda n: n.lower().startswith("bug") and n.endswith(".md")


def sizes():
    out = {}
    for n in os.listdir(DIRECTORY):
        if is_bug(n):
            try:
                out[n] = os.path.getsize(os.path.join(DIRECTORY, n))
            except OSError:
                pass
    return out


known = sizes()               # name -> size already reported
pending = {}                  # name -> deadline (monotonic) to flush
dead = set()                  # names seen deleted

print(f"watching {DIRECTORY} for BUG*.md (inotify, no sleep, no tmux)", flush=True)
for n in sorted(known):
    print(f"  present: {n} ({known[n]} bytes)", flush=True)

while True:
    timeout = None
    if pending:
        timeout = max(0.0, min(pending.values()) - time.monotonic())
    r, _, _ = select.select([fd], [], [], timeout)

    if r:
        data = os.read(fd, 8192)
        i = 0
        while i < len(data):
            _wd, mask, _cookie, ln = struct.unpack_from("iIII", data, i)
            name = data[i + E:i + E + ln].split(b"\0", 1)[0].decode(errors="replace")
            i += E + ln
            if not name or not is_bug(name):
                continue
            if mask & IN_DELETE:
                dead.add(name)
                pending[name] = time.monotonic()   # flush immediately
            else:
                pending[name] = time.monotonic() + QUIET

    now = time.monotonic()
    for name, due in list(pending.items()):
        if due > now:
            continue
        del pending[name]
        path = os.path.join(DIRECTORY, name)
        try:
            sz = os.path.getsize(path)
        except OSError:
            if name in known:
                print(f"\n=== DELETE: {name} ===", flush=True)
                known.pop(name, None)
            dead.discard(name)
            continue
        if name in dead:
            dead.discard(name)
            continue
        old = known.get(name)
        if old is None:
            print(f"\n=== NEW: {name} ({sz} bytes) ===", flush=True)
            if sz:
                with open(path, errors="replace") as f:
                    print(f.read(), flush=True)
        elif sz > old:
            print(f"\n=== APPEND: {name} (+{sz - old} bytes) ===", flush=True)
            with open(path, errors="replace") as f:
                f.seek(old)
                print(f.read(), flush=True)
        elif sz < old:
            print(f"\n=== TRUNCATED: {name} (now {sz} bytes) ===", flush=True)
        known[name] = sz
