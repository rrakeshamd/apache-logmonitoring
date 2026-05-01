import glob
import os
import queue
import subprocess
import threading
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LogTailer:
    """Tails one log file and broadcasts each line to all subscribed client queues."""

    def __init__(self, log_path: str, queue_maxsize: int = 500):
        self.log_path  = log_path
        self._clients  = []
        self._lock     = threading.Lock()
        self._stop_evt = threading.Event()
        self._maxsize  = queue_maxsize
        self._thread   = threading.Thread(
            target=self._run, daemon=True, name=f'tailer-{Path(log_path).name}'
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_evt.set()

    def subscribe(self) -> queue.Queue:
        """Return a new per-client queue. Caller must call unsubscribe() when done."""
        q = queue.Queue(maxsize=self._maxsize)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            try:
                self._clients.remove(q)
            except ValueError:
                pass

    def _broadcast(self, line: str):
        with self._lock:
            for q in self._clients:
                try:
                    q.put_nowait(line)
                except queue.Full:
                    pass  # slow client — drop this line for them only

    def _run(self):
        while not self._stop_evt.is_set():
            if not Path(self.log_path).exists():
                logger.warning("Log file not found: %s — retrying in 5s", self.log_path)
                time.sleep(5)
                continue

            logger.info("Starting tail on %s", self.log_path)
            try:
                proc = subprocess.Popen(
                    # stdbuf -oL: line-buffer stdout so readline() unblocks immediately
                    # tail -F: follow by name, handles log rotation
                    # tail -n 50: emit last 50 lines on connect so page isn't blank
                    ['stdbuf', '-oL', 'tail', '-F', '-n', '50', self.log_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                for line in proc.stdout:
                    if self._stop_evt.is_set():
                        break
                    stripped = line.rstrip('\n')
                    if stripped:
                        self._broadcast(stripped)
                proc.wait()
            except Exception as e:
                logger.error("Tailer error on %s: %s", self.log_path, e)
                time.sleep(2)


class LogTailerRegistry:
    """Manages one LogTailer per *.log file found in LOG_DIR."""

    def __init__(self, config):
        self._tailers = {}
        self._lock    = threading.Lock()
        self._log_dir = config.get('LOG_DIR', '/var/log/apache2')
        self._maxsize = config.get('SSE_QUEUE_MAXSIZE', 500)

    def start(self):
        """Discover all *.log files in LOG_DIR and start a tailer for each."""
        self.refresh()

    def refresh(self):
        """Re-scan LOG_DIR and start tailers for any newly discovered log files."""
        pattern = os.path.join(self._log_dir, '*.log')
        found   = sorted(glob.glob(pattern))
        with self._lock:
            for path in found:
                name = os.path.splitext(os.path.basename(path))[0]
                if name not in self._tailers:
                    tailer = LogTailer(path, self._maxsize)
                    tailer.start()
                    self._tailers[name] = tailer
                    logger.info("Registered log: %s → %s", name, path)
        if not found:
            logger.warning("No *.log files found in %s", self._log_dir)

    def get(self, name: str):
        with self._lock:
            return self._tailers.get(name)

    def all_names(self):
        with self._lock:
            return sorted(self._tailers.keys())

    def all_info(self):
        """Return list of dicts with name, path, size_bytes for each tailer."""
        result = []
        with self._lock:
            for name, tailer in sorted(self._tailers.items()):
                try:
                    size = os.path.getsize(tailer.log_path)
                except OSError:
                    size = 0
                result.append({'name': name, 'path': tailer.log_path, 'size_bytes': size})
        return result
