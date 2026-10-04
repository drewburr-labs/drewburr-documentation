#!/usr/bin/env python3
"""Ramp concurrent IPTV streams one at a time to find the provider's connection limit.

Opens stream N, waits, then checks that every open stream is still receiving data.
Stops at the first refusal/stall or at MAX_STREAMS, then closes everything.
Never prints stream URLs (they embed account credentials).
"""
import re, sys, threading, time, urllib.request, urllib.error

PLAYLIST = "data/latest.m3u"
GROUP = "USA Premium"
MAX_STREAMS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
SETTLE = 15  # seconds after opening each stream before checking all of them
WINDOW = 5   # a stream is "alive" if it received bytes in the last WINDOW seconds


class Stream(threading.Thread):
    def __init__(self, name, url):
        super().__init__(daemon=True)
        self.name, self.url = name, url
        self.bytes, self.last_rx, self.status, self.error = 0, 0.0, None, None
        self.stop = threading.Event()

    def run(self):
        try:
            with urllib.request.urlopen(self.url, timeout=15) as r:
                self.status = r.status
                while not self.stop.is_set():
                    chunk = r.read(65536)
                    if not chunk:
                        self.error = "EOF (server closed)"
                        return
                    self.bytes += len(chunk)
                    self.last_rx = time.time()
        except urllib.error.HTTPError as e:
            self.status, self.error = e.code, f"HTTP {e.code}"
        except Exception as e:
            self.error = re.sub(r"https?://\S+", "<url>", f"{type(e).__name__}: {e}")

    def alive(self):
        return self.error is None and time.time() - self.last_rx < WINDOW


lines = open(PLAYLIST, encoding="utf-8", errors="replace").read().splitlines()
channels = [(lines[i].rsplit(",", 1)[-1].strip(), lines[i + 1])
            for i in range(len(lines) - 1)
            if f'group-title="{GROUP}"' in lines[i] and lines[i + 1].startswith("http")]

streams = []
try:
    for n in range(1, MAX_STREAMS + 1):
        s = Stream(*channels[n - 1])
        s.start()
        streams.append(s)
        time.sleep(SETTLE)
        print(f"--- {n} open")
        for x in streams:
            print(f"  {x.name:32} {'OK ' if x.alive() else 'DEAD'} status={x.status} "
                  f"rx={x.bytes / 1e6:6.1f}MB {x.error or ''}")
        if not all(x.alive() for x in streams):
            print(f"RESULT: failure at {n} concurrent -> limit is likely {n - 1}")
            break
    else:
        print(f"RESULT: {MAX_STREAMS} concurrent all healthy (limit >= {MAX_STREAMS})")
finally:
    for x in streams:
        x.stop.set()
    time.sleep(1)
    print("all streams closed")
