"""Briefly reuse provider responses across both conversation modes."""
from copy import deepcopy
from threading import Lock
from time import monotonic


class LiveSnapshots:
    def __init__(self):
        self.entries = {}
        self.lock = Lock()

    def get(self, key, fetch):
        with self.lock:
            now = monotonic()
            self.entries = {k: entry for k, entry in self.entries.items() if entry[0] > now}
            if key in self.entries:
                return deepcopy(self.entries[key][1])
        value = fetch()
        with self.lock:
            ttl = 15 if value["status"] == "unavailable" else 120
            if len(self.entries) >= 64:
                self.entries.pop(next(iter(self.entries)))
            # If another arm finished first, serve the same checked snapshot.
            entry = self.entries.setdefault(key, (monotonic() + ttl, value))
            return deepcopy(entry[1])
