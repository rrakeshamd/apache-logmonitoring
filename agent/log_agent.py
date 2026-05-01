#!/usr/bin/env python3
"""
Apache Log Agent — install on remote Linux servers.

Usage:
    python3 log_agent.py \
        --server web-01 \
        --server-url http://192.168.1.100:5001 \
        --agent-key changeme \
        --logs access:/var/log/apache2/access.log \
        --logs error:/var/log/apache2/error.log

Each --logs argument is  <log_name>:<log_path>.
The agent tails each log file and streams lines to the central
monitoring server via POST /api/agent/push.

No external dependencies — stdlib only.
"""

import argparse
import json
import logging
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('log_agent')


# ── HTTP sender ───────────────────────────────────────────────────────────────

class Sender:
    """Sends log lines to the central server with retry/backoff."""

    def __init__(self, server_url: str, server_name: str, agent_key: str):
        self.push_url    = server_url.rstrip('/') + '/api/agent/push'
        self.server_name = server_name
        self.agent_key   = agent_key

    def send(self, log_name: str, line: str) -> bool:
        """POST one log line. Returns True on success, False on failure."""
        payload = json.dumps({
            'server':   self.server_name,
            'log_name': log_name,
            'line':     line,
        }).encode('utf-8')

        req = urllib.request.Request(
            self.push_url,
            data=payload,
            method='POST',
            headers={
                'Content-Type': 'application/json',
                'X-Agent-Key':  self.agent_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204)
        except urllib.error.HTTPError as e:
            logger.error("HTTP %s from server: %s", e.code, e.reason)
            return False
        except Exception as e:
            logger.error("Send error: %s", e)
            return False


# ── Per-log tailer thread ─────────────────────────────────────────────────────

class LogTailerThread(threading.Thread):
    """Tails one log file and pushes each line to the central server."""

    def __init__(self, log_name: str, log_path: str, sender: Sender):
        super().__init__(daemon=True, name=f'tailer-{log_name}')
        self.log_name = log_name
        self.log_path = log_path
        self.sender   = sender
        self._stop    = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        backoff = 2
        while not self._stop.is_set():
            if not Path(self.log_path).exists():
                logger.warning("Log not found: %s — retrying in %ss", self.log_path, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue

            backoff = 2
            logger.info("Tailing %s (%s)", self.log_name, self.log_path)
            try:
                proc = subprocess.Popen(
                    ['stdbuf', '-oL', 'tail', '-F', '-n', '50', self.log_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                for raw_line in proc.stdout:
                    if self._stop.is_set():
                        break
                    line = raw_line.rstrip('\n')
                    if not line:
                        continue
                    # Retry send with backoff until the line gets through
                    send_backoff = 1
                    while not self.sender.send(self.log_name, line):
                        if self._stop.is_set():
                            break
                        logger.warning(
                            "Send failed for %s — retrying in %ss", self.log_name, send_backoff
                        )
                        time.sleep(send_backoff)
                        send_backoff = min(send_backoff * 2, 30)
                proc.wait()
            except Exception as e:
                logger.error("Tailer error on %s: %s", self.log_path, e)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description='Stream Apache logs to a central monitoring server.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--server',     required=True,
                   help='Name for this server (shown in GUI), e.g. web-01')
    p.add_argument('--server-url', required=True,
                   help='Base URL of the central monitoring app, e.g. http://192.168.1.100:5001')
    p.add_argument('--agent-key',  default='changeme',
                   help='Shared secret matching AGENT_SECRET on the central server')
    p.add_argument('--logs',       required=True, action='append', metavar='NAME:PATH',
                   help='Log to tail in name:path format. Repeat for multiple logs.')
    return p.parse_args()


def main():
    args = parse_args()

    # Parse --logs name:/path pairs
    log_pairs = []
    for entry in args.logs:
        if ':' not in entry:
            print(f"ERROR: --logs must be in NAME:PATH format, got: {entry}", file=sys.stderr)
            sys.exit(1)
        name, path = entry.split(':', 1)
        log_pairs.append((name.strip(), path.strip()))

    sender  = Sender(args.server_url, args.server, args.agent_key)
    threads = []

    for log_name, log_path in log_pairs:
        t = LogTailerThread(log_name, log_path, sender)
        t.start()
        threads.append(t)
        logger.info("Started tailer: %s → %s", log_name, log_path)

    logger.info(
        "Agent '%s' running — streaming to %s (%d log(s))",
        args.server, args.server_url, len(threads)
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down…")
        for t in threads:
            t.stop()


if __name__ == '__main__':
    main()
