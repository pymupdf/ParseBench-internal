"""Temporary forensics (run branch only), injected via PYTHONPATH.

Loaded automatically by every Python in the job. Once the process's own RSS
crosses 3 GB, dump all-thread stacks to stderr every 2 s — the last dump
before the cgroup SIGKILL identifies the allocating code path.
"""
import faulthandler
import sys
import threading
import time


def _rss_gb():
    try:
        with open("/proc/self/status", encoding="ascii", errors="ignore") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1e6
    except OSError:
        pass
    return 0.0


def _watch():
    while True:
        rss = _rss_gb()
        if rss > 3.0:
            print(f"[stack-watch] RSS={rss:.2f}GB", file=sys.stderr, flush=True)
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            time.sleep(2)
        else:
            time.sleep(1)


threading.Thread(target=_watch, daemon=True).start()
