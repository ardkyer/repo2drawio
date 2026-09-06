"""Bounded, single-process request admission for small self-hosted deployments."""
from collections import deque
import threading
import time


class RateLimiter:
    def __init__(self, limit=3, window=60, max_clients=4096):
        self.limit, self.window, self.max_clients = limit, window, max_clients
        self.clients = {}
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self.lock:
            for client in list(self.clients):
                events = self.clients[client]
                while events and events[0] <= now - self.window:
                    events.popleft()
                if not events:
                    del self.clients[client]
            if key not in self.clients and len(self.clients) >= self.max_clients:
                return False
            events = self.clients.setdefault(key, deque())
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


class CapacityError(ValueError):
    pass
