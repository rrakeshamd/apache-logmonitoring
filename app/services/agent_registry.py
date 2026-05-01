import queue
import threading
import logging

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Manages in-memory queues for log lines pushed by remote agents.

    Keyed by (server_name, log_name). Multiple SSE clients can subscribe
    to the same (server, log) pair — each gets its own queue.
    """

    def __init__(self, queue_maxsize: int = 500):
        self._maxsize  = queue_maxsize
        self._clients  = {}   # (server, log_name) -> [queue, ...]
        self._servers  = {}   # server -> set of log_names seen
        self._lock     = threading.Lock()

    def push(self, server: str, log_name: str, line: str):
        """Broadcast a raw log line to all subscribers of (server, log_name)."""
        key = (server, log_name)
        with self._lock:
            # Track server/log metadata
            if server not in self._servers:
                self._servers[server] = set()
                logger.info("New agent connected: %s", server)
            if log_name not in self._servers[server]:
                self._servers[server].add(log_name)
                logger.info("New log registered: %s/%s", server, log_name)

            queues = self._clients.get(key, [])
            for q in queues:
                try:
                    q.put_nowait(line)
                except queue.Full:
                    pass  # slow client — drop line, don't block

    def subscribe(self, server: str, log_name: str) -> queue.Queue:
        """Return a new per-client queue. Caller must call unsubscribe() when done."""
        q   = queue.Queue(maxsize=self._maxsize)
        key = (server, log_name)
        with self._lock:
            self._clients.setdefault(key, []).append(q)
        return q

    def unsubscribe(self, server: str, log_name: str, q: queue.Queue):
        key = (server, log_name)
        with self._lock:
            clients = self._clients.get(key, [])
            try:
                clients.remove(q)
            except ValueError:
                pass

    def registered_servers(self) -> list:
        with self._lock:
            return sorted(self._servers.keys())

    def registered_logs(self, server: str) -> list:
        with self._lock:
            return sorted(self._servers.get(server, set()))
