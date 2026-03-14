# Run with: python test_pool_concurrency.py
# No dependencies beyond Python 3.10+ stdlib required.

import threading
import unittest
import time
from contextlib import contextmanager


# ---------------------------------------------------------------------------
# Test doubles (no psycopg2 or FastAPI required)
# ---------------------------------------------------------------------------

class PoolError(Exception):
    """Test double for psycopg2_pool.PoolError."""


class HTTPException(Exception):
    """Test double for fastapi.HTTPException."""
    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# FakeConnection
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


# ---------------------------------------------------------------------------
# FakePool
# ---------------------------------------------------------------------------

class FakePool:
    """
    Thread-safe fake pool that mirrors ThreadedConnectionPool's API.
    Tracks concurrent ownership to detect any collision.
    """

    def __init__(self, size: int):
        self._lock = threading.Lock()
        self._available: list[FakeConnection] = [FakeConnection(i) for i in range(size)]
        self._in_use: dict[int, int] = {}       # conn_id → thread_id currently holding it
        self.collision_log: list[tuple] = []    # (conn_id, thread_id_a, thread_id_b) triples
        self.checkout_log: list[tuple] = []     # (conn_id, thread_id) at every getconn()

    def getconn(self) -> FakeConnection:
        with self._lock:
            if not self._available:
                raise PoolError("connection pool exhausted")
            conn = self._available.pop()
            tid = threading.get_ident()
            # Detect collision: same conn already in use by another thread
            if conn.conn_id in self._in_use:
                other_tid = self._in_use[conn.conn_id]
                self.collision_log.append((conn.conn_id, other_tid, tid))
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
# Inline copy of get_db_conn (avoids importing main.py)
# ---------------------------------------------------------------------------

@contextmanager
def get_db_conn(pool, HTTPExc=HTTPException, PoolErr=PoolError):
    """Inline copy of main.py get_db_conn for testing without imports."""
    try:
        conn = pool.getconn()
    except PoolErr:
        raise HTTPExc(status_code=503, detail="Pool exhausted")
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


# ---------------------------------------------------------------------------
# TEST 1 — Regression: shared connection causes detectable collision
# ---------------------------------------------------------------------------

class TestSharedConnectionRaceCondition(unittest.TestCase):
    """
    Prove that the OLD pattern (one shared connection object for all threads)
    produces a detectable signal: every thread records the same id().
    This is the race condition that the pool refactor eliminates.
    """

    def test_shared_connection_all_threads_get_same_id(self):
        NUM_THREADS = 8
        shared_conn = FakeConnection(conn_id=99)
        connection_ids_seen: list[int] = []
        lock = threading.Lock()
        barrier = threading.Barrier(NUM_THREADS)

        def worker():
            barrier.wait()  # all threads enter simultaneously
            # OLD pattern: every thread uses the same shared object
            conn = shared_conn
            with lock:
                connection_ids_seen.append(id(conn))

        threads = [threading.Thread(target=worker) for _ in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads shared the same object → exactly one distinct id
        self.assertEqual(
            len(set(connection_ids_seen)), 1,
            "Expected all threads to see the same connection id (old race condition signal)",
        )
        self.assertEqual(len(connection_ids_seen), NUM_THREADS)


# ---------------------------------------------------------------------------
# TEST 2 — Correctness: pool issues distinct connections per thread
# ---------------------------------------------------------------------------

class TestPoolIssuesDistinctConnections(unittest.TestCase):
    """
    Prove that get_db_conn() gives each concurrent caller a unique connection
    and that no two threads ever hold the same object simultaneously.
    """

    POOL_SIZE = 5

    def test_distinct_connections_no_sharing_full_return(self):
        pool = FakePool(self.POOL_SIZE)
        barrier = threading.Barrier(self.POOL_SIZE)
        connection_ids_seen: list[int] = []
        thread_ids_seen: list[int] = []
        lock = threading.Lock()

        def worker():
            barrier.wait()  # all threads call getconn() at the same instant
            with get_db_conn(pool) as conn:
                with lock:
                    connection_ids_seen.append(conn.conn_id)
                    thread_ids_seen.append(threading.get_ident())
                time.sleep(0.05)  # hold the connection for 50 ms

        threads = [threading.Thread(target=worker) for _ in range(self.POOL_SIZE)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # a) Every thread received a different connection object
        self.assertEqual(
            len(set(connection_ids_seen)), self.POOL_SIZE,
            "Each thread must receive a distinct connection",
        )

        # b) No simultaneous sharing detected by FakePool's ownership tracker
        self.assertEqual(
            len(pool.collision_log), 0,
            f"Collisions detected: {pool.collision_log}",
        )

        # c) All connections returned to the pool
        self.assertEqual(
            pool.available_count(), self.POOL_SIZE,
            "All connections must be returned after threads complete",
        )

        # d) Thread affinity: each conn_id maps to exactly one thread_id
        #    Build a mapping from checkout_log and verify no conn_id has two owners
        conn_to_threads: dict[int, set[int]] = {}
        for conn_id, tid in pool.checkout_log:
            conn_to_threads.setdefault(conn_id, set()).add(tid)
        for conn_id, tids in conn_to_threads.items():
            self.assertEqual(
                len(tids), 1,
                f"Connection {conn_id} was held by multiple threads: {tids}",
            )


# ---------------------------------------------------------------------------
# TEST 3 — Pool exhaustion returns 503
# ---------------------------------------------------------------------------

class TestPoolExhaustionRaises503(unittest.TestCase):
    """
    Prove that when the pool is exhausted, get_db_conn() raises an exception
    with status_code == 503 rather than crashing with an unhandled PoolError.
    """

    POOL_SIZE = 2

    def test_pool_error_raised_when_exhausted(self):
        pool = FakePool(self.POOL_SIZE)

        # Exhaust the pool manually
        conn_a = pool.getconn()
        conn_b = pool.getconn()

        # Third checkout must raise PoolError
        with self.assertRaises(PoolError):
            pool.getconn()

        # Return connections so the pool is clean for the next assertion
        pool.putconn(conn_a)
        pool.putconn(conn_b)

    def test_get_db_conn_raises_503_on_exhaustion(self):
        pool = FakePool(self.POOL_SIZE)

        # Exhaust pool by checking out all connections without returning them
        held = [pool.getconn() for _ in range(self.POOL_SIZE)]

        exc_raised: list[HTTPException] = []
        try:
            with get_db_conn(pool) as _conn:
                pass  # should never reach here
        except HTTPException as exc:
            exc_raised.append(exc)

        self.assertEqual(len(exc_raised), 1, "Expected exactly one HTTPException")
        self.assertEqual(
            exc_raised[0].status_code, 503,
            f"Expected 503, got {exc_raised[0].status_code}",
        )

        # Clean up
        for c in held:
            pool.putconn(c)


# ---------------------------------------------------------------------------
# TEST 4 — Context manager returns connection on exception
# ---------------------------------------------------------------------------

class TestConnectionReturnedOnException(unittest.TestCase):
    """
    Prove that get_db_conn() returns the connection to the pool even when
    the body of the with block raises, and that rollback() is called.
    """

    def test_connection_returned_and_rollback_called_on_exception(self):
        pool = FakePool(size=1)
        self.assertEqual(pool.available_count(), 1)

        fake_conn: list[FakeConnection] = []

        with self.assertRaises(RuntimeError):
            with get_db_conn(pool) as conn:
                fake_conn.append(conn)
                raise RuntimeError("simulated query failure")

        # Connection must be back in the pool
        self.assertEqual(
            pool.available_count(), 1,
            "Connection must be returned to the pool after an exception",
        )

        # rollback() must have been called exactly once
        self.assertEqual(
            fake_conn[0].rollback_count, 1,
            "rollback() must be called exactly once on the error path",
        )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
