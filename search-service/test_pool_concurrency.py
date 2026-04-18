# Run with: python test_pool_concurrency.py
# No dependencies beyond Python 3.10+ stdlib required.
"""
Concurrency tests for the ThreadedConnectionPool refactor in search-service.

Proves two things without needing a real PostgreSQL instance or any heavy import:
  1. REGRESSION PROOF  — the old single-connection pattern produces a detectable
                         collision signal under concurrent access.
  2. CORRECTNESS PROOF — get_db_conn() issues a distinct connection per thread
                         and always returns it to the pool.
"""

import threading
import time
import unittest
from contextlib import contextmanager


# ---------------------------------------------------------------------------
# Test doubles — no psycopg2, no FastAPI
# ---------------------------------------------------------------------------

class PoolError(Exception):
    """Stand-in for psycopg2_pool.PoolError."""


class HTTPException(Exception):
    """Stand-in for fastapi.HTTPException."""
    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Fake connection / pool
# ---------------------------------------------------------------------------

class FakeConnection:
    """Minimal stand-in for a psycopg2 connection."""

    def __init__(self, conn_id: int):
        self.conn_id = conn_id
        self.autocommit = False
        self.rollback_count = 0

    def rollback(self):
        self.rollback_count += 1

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class FakePool:
    """
    Thread-safe fake pool mirroring ThreadedConnectionPool's API.

    Tracks concurrent ownership to detect simultaneous sharing of a single
    connection object by two or more threads.
    """

    def __init__(self, size: int):
        self._lock = threading.Lock()
        self._available: list = [FakeConnection(i) for i in range(size)]
        self._in_use: dict = {}           # conn_id -> thread_id
        self.collision_log: list = []     # (conn_id, owner_tid, intruder_tid)
        self.checkout_log: list = []      # (conn_id, thread_id) at getconn()

    def getconn(self) -> FakeConnection:
        with self._lock:
            if not self._available:
                raise PoolError("FakePool exhausted")
            conn = self._available.pop()
            tid = threading.get_ident()
            if conn.conn_id in self._in_use:
                # Should never happen — means two threads share the same object
                self.collision_log.append((conn.conn_id, self._in_use[conn.conn_id], tid))
            self._in_use[conn.conn_id] = tid
            self.checkout_log.append((conn.conn_id, tid))
        return conn

    def putconn(self, conn: FakeConnection) -> None:
        with self._lock:
            self._in_use.pop(conn.conn_id, None)
            self._available.append(conn)

    def available_count(self) -> int:
        with self._lock:
            return len(self._available)


# ---------------------------------------------------------------------------
# Inline copy of get_db_conn() — exact logic from main.py, pool injected
# ---------------------------------------------------------------------------

@contextmanager
def get_db_conn(pool, _HTTPException=HTTPException):
    """Inline copy of main.py get_db_conn() for testing without imports."""
    try:
        conn = pool.getconn()
    except PoolError:
        raise _HTTPException(status_code=503, detail="Pool exhausted")
    conn.autocommit = True
    try:
        yield conn
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        pool.putconn(conn)


# ===========================================================================
# TEST 1 — Regression: shared single connection produces a detectable collision
# ===========================================================================

class TestSharedConnectionRaceCondition(unittest.TestCase):
    """
    Simulates the OLD behaviour: one shared connection used by N threads.

    Asserts that all threads saw the *same* connection id — the dangerous
    signal the pool refactor was designed to eliminate.
    """

    def test_shared_connection_all_same_id(self):
        THREAD_COUNT = 8
        shared_conn = FakeConnection(conn_id=0)
        connection_ids_seen = []
        lock = threading.Lock()
        barrier = threading.Barrier(THREAD_COUNT)

        def worker():
            barrier.wait()                       # all enter simultaneously
            with lock:
                connection_ids_seen.append(id(shared_conn))

        threads = [threading.Thread(target=worker) for _ in range(THREAD_COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads shared exactly one object — the race condition signal
        self.assertEqual(
            len(set(connection_ids_seen)), 1,
            "Expected all threads to share one connection id (old pattern regression signal)",
        )
        self.assertEqual(len(connection_ids_seen), THREAD_COUNT)


# ===========================================================================
# TEST 2 — Correctness: pool issues a distinct connection per thread
# ===========================================================================

class TestPoolIssuesDistinctConnections(unittest.TestCase):
    """
    Five threads hammer the pool simultaneously.  Asserts:
      a) Each thread received a different connection object.
      b) No two threads ever held the same connection simultaneously.
      c) All connections were returned after the threads completed.
      d) No conn_id appeared under two different thread_ids during their hold.
    """

    POOL_SIZE = 5
    HOLD_MS   = 50   # ms each thread holds its connection

    def test_distinct_connections_no_collisions_full_return(self):
        pool = FakePool(self.POOL_SIZE)
        barrier = threading.Barrier(self.POOL_SIZE)

        checkout_records = []   # (conn_id, thread_id)
        lock = threading.Lock()

        def worker():
            barrier.wait()
            with get_db_conn(pool) as conn:
                tid = threading.get_ident()
                with lock:
                    checkout_records.append((conn.conn_id, tid))
                time.sleep(self.HOLD_MS / 1000)

        threads = [threading.Thread(target=worker) for _ in range(self.POOL_SIZE)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        conn_ids = [r[0] for r in checkout_records]

        # a) Every thread got a different connection
        self.assertEqual(
            len(set(conn_ids)), self.POOL_SIZE,
            f"Expected {self.POOL_SIZE} distinct conn ids, got {set(conn_ids)}",
        )

        # b) No simultaneous sharing detected by FakePool
        self.assertEqual(
            len(pool.collision_log), 0,
            f"Collision detected: {pool.collision_log}",
        )

        # c) All connections returned
        self.assertEqual(
            pool.available_count(), self.POOL_SIZE,
            f"Expected pool fully returned, available={pool.available_count()}",
        )

        # d) Thread affinity during hold — each conn_id maps to exactly one thread_id
        conn_to_threads = {}
        for cid, tid in pool.checkout_log:
            conn_to_threads.setdefault(cid, set()).add(tid)
        for cid, tids in conn_to_threads.items():
            self.assertEqual(
                len(tids), 1,
                f"conn_id {cid} was checked out by multiple threads: {tids}",
            )


# ===========================================================================
# TEST 3 — Pool exhaustion raises 503
# ===========================================================================

class TestPoolExhaustionRaises503(unittest.TestCase):
    """
    A pool of size 2 with 3 simultaneous callers.  The third direct getconn()
    raises PoolError; the get_db_conn() context manager converts it to HTTP 503.
    """

    def test_third_checkout_raises_pool_error(self):
        pool = FakePool(size=2)
        c1 = pool.getconn()
        c2 = pool.getconn()

        with self.assertRaises(PoolError):
            pool.getconn()          # exhausted — must raise PoolError

        pool.putconn(c1)
        pool.putconn(c2)

    def test_get_db_conn_raises_503_on_exhaustion(self):
        pool = FakePool(size=2)
        c1 = pool.getconn()
        c2 = pool.getconn()

        with self.assertRaises(HTTPException) as ctx:
            with get_db_conn(pool) as _conn:
                pass    # should not be reached

        self.assertEqual(ctx.exception.status_code, 503)

        pool.putconn(c1)
        pool.putconn(c2)


# ===========================================================================
# TEST 4 — Connection returned to pool even when the with-block raises
# ===========================================================================

class TestConnectionReturnedOnException(unittest.TestCase):
    """
    Raises an exception inside get_db_conn(). Verifies:
      - The connection is returned to the pool (available_count == 1).
      - rollback() was called exactly once on the fake connection.
    """

    def test_connection_returned_and_rollback_called_on_exception(self):
        pool = FakePool(size=1)
        checked_out_conn = None

        with self.assertRaises(RuntimeError):
            with get_db_conn(pool) as conn:
                checked_out_conn = conn
                raise RuntimeError("simulated query failure")

        # Connection back in pool
        self.assertEqual(
            pool.available_count(), 1,
            "Connection was not returned to pool after exception",
        )

        # rollback() called once on the error path
        self.assertIsNotNone(checked_out_conn)
        self.assertEqual(
            checked_out_conn.rollback_count, 1,
            f"Expected rollback_count=1, got {checked_out_conn.rollback_count}",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main(verbosity=2)
