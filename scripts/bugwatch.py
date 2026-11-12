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


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sizes():
    out = {}
    for n in os.listdir(DIRECTORY):
        if is_bug(n):
            path = os.path.join(DIRECTORY, n)
            try:
                out[n] = (os.path.getsize(path), _sha(path))
            except OSError:
                pass
    return out


known = sizes()               # name -> (size, sha) already reported
pending = {}                  # name -> deadline (monotonic) to flush
dead = set()                  # names seen deleted

print(f"watching {DIRECTORY} for BUG*.md (inotify, no sleep, no tmux)", flush=True)
for n in sorted(known):
    print(f"  present: {n} ({known[n][0]} bytes)", flush=True)

while True:
    timeout = None
    if pending:
        timeout = max(0.0, min(pending.values()) - time.monotonic())
    r, _, _ = select.select([fd], [], [], timeout)

    if r:
        # Drain the WHOLE inotify queue before flushing. One save emits several
        # raw events (CREATE/MODIFY*n/CLOSE_WRITE); reading only one per loop
        # iteration flushed the same change again on the next iteration, which
        # is why one edit printed three identical APPENDs.
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
                _wd, mask, _cookie, ln = struct.unpack_from("iIII", data, i)
                name = data[i + E:i + E + ln].split(b"\0", 1)[0].decode(errors="replace")
                i += E + ln
                if not name or not is_bug(name):
                    continue
                if mask & IN_DELETE:
                    dead.add(name)
                    pending.setdefault(name, time.monotonic())  # flush immediately
                else:
                    # Do not extend a pending deadline: keep the earliest, so a
                    # burst of events for one save flushes once.
                    pending.setdefault(name, time.monotonic() + QUIET)

    now = time.monotonic()
    for name, due in list(pending.items()):
        if due > now:
            continue
        del pending[name]
        path = os.path.join(DIRECTORY, name)
        try:
            sz = os.path.getsize(path)
            sha = _sha(path)
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
        else:
            old_sz, old_sha = old
            if sha == old_sha:
                known[name] = (sz, sha)
                continue
            appended = False
            if sz > old_sz:
                # APPEND only if the old prefix is byte-identical; a truncating
                # rewrite can also grow the file (e.g. 5-byte "test\n" -> 6-byte
                # "test2\n"), which is NOT an append and must not be read from
                # the old offset.
                try:
                    with open(path, "rb") as f:
                        prefix = f.read(old_sz)
                    import hashlib
                    appended = hashlib.sha256(prefix).hexdigest() == old_sha
                except OSError:
                    appended = False
            if appended:
                print(f"\n=== APPEND: {name} (+{sz - old_sz} bytes) ===", flush=True)
                with open(path, errors="replace") as f:
                    f.seek(old_sz)
                    print(f.read(), flush=True)
            else:
                print(f"\n=== REWRITE: {name} (now {sz} bytes) ===", flush=True)
                if sz:
                    with open(path, errors="replace") as f:
                        print(f.read(), flush=True)
        known[name] = (sz, sha)
