"""One asyncio.Lock per key (a match), so matches never serialize each other."""
import asyncio
import weakref


class KeyedLocks:
    def __init__(self):
        # Unused locks drop out; a holder or waiter keeps its lock alive.
        self._locks = weakref.WeakValueDictionary()

    def __call__(self, key):
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock
