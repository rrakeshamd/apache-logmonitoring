#!/usr/bin/env python3
"""
Generates realistic Apache access and error log lines to test files.

Usage (directory mode — recommended):
    python3 tools/simulate_logs.py --dir /tmp/testlogs --rate 1
    # Creates: access.log, error.log, ssl_error.log, php_error.log inside /tmp/testlogs
    # Then run: LOG_DIR=/tmp/testlogs python3 run.py

Legacy (individual file mode):
    python3 tools/simulate_logs.py --access /tmp/access.log --error /tmp/error.log --rate 2
"""
import argparse
import os
import random
import sys
import time
from datetime import datetime

METHODS       = ['GET', 'POST', 'PUT', 'DELETE', 'HEAD']
PATHS         = [
    '/index.html', '/api/users', '/api/products', '/static/app.js',
    '/login', '/logout', '/admin', '/favicon.ico', '/robots.txt',
    '/api/orders/123', '/upload', '/.env', '/wp-admin',
]
STATUSES      = [200]*10 + [201]*2 + [301]*1 + [304]*3 + [400]*2 + [403]*2 + [404]*4 + [500]*2 + [503]*1
USER_AGENTS   = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36',
    'curl/7.88.1',
    'python-requests/2.31.0',
    'Googlebot/2.1 (+http://www.google.com/bot.html)',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
    'Wget/1.21.4',
]
ERROR_LEVELS  = ['error', 'warn', 'notice', 'info', 'crit', 'alert']
ERROR_MODULES = ['core', 'authz_core', 'proxy', 'ssl', 'php', 'rewrite']
ERROR_MSGS    = [
    'File does not exist: /var/www/html/favicon.ico',
    'Permission denied: /var/www/html/admin',
    'ProxyPass connection refused to backend:8080',
    'SSL handshake failed',
    'PHP Fatal error: Call to undefined function',
    'client denied by server configuration: /var/www/html/.env',
    'AH00162: server is within MinSpareThreads of MaxRequestWorkers, consider raising the MaxRequestWorkers setting',
    'Certificate verification failed: unable to get local issuer certificate',
    'Invalid URI in request GET /.git/config HTTP/1.1',
    'Timeout waiting for output from CGI script',
]


def access_line() -> str:
    ip     = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
    ts     = datetime.now().strftime('%d/%b/%Y:%H:%M:%S +0000')
    method = random.choice(METHODS)
    path   = random.choice(PATHS)
    status = random.choice(STATUSES)
    size   = random.randint(150, 80000) if status not in (204, 304) else 0
    ua     = random.choice(USER_AGENTS)
    return f'{ip} - - [{ts}] "{method} {path} HTTP/1.1" {status} {size} "-" "{ua}"'


def error_line() -> str:
    ts      = datetime.now().strftime('%a %b %d %H:%M:%S.%f %Y')
    level   = random.choice(ERROR_LEVELS)
    module  = random.choice(ERROR_MODULES)
    pid     = random.randint(1000, 32767)
    ip      = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
    msg     = random.choice(ERROR_MSGS)
    return f'[{ts}] [{module}:{level}] [pid {pid}] [client {ip}:54321] {msg}'


def main():
    parser = argparse.ArgumentParser(description='Apache log simulator')
    parser.add_argument('--dir',    default=None,                   help='Directory to write multiple *.log files into')
    parser.add_argument('--access', default='/tmp/test_access.log', help='Access log path (legacy single-file mode)')
    parser.add_argument('--error',  default='/tmp/test_error.log',  help='Error log path (legacy single-file mode)')
    parser.add_argument('--rate',   type=float, default=0.5,
                        help='Lines per second (default 0.5 = one every 2s)')
    args = parser.parse_args()

    if args.dir:
        # Directory mode: write multiple .log files so the app discovers them all
        os.makedirs(args.dir, exist_ok=True)
        files = {
            'access':    open(os.path.join(args.dir, 'access.log'),    'a', buffering=1),
            'error':     open(os.path.join(args.dir, 'error.log'),     'a', buffering=1),
            'ssl_error': open(os.path.join(args.dir, 'ssl_error.log'), 'a', buffering=1),
            'php_error': open(os.path.join(args.dir, 'php_error.log'), 'a', buffering=1),
        }
        print(f"Writing logs to directory: {args.dir}")
        for name, fh in files.items():
            print(f"  {name}.log → {fh.name}")
        print(f"Rate: {args.rate} lines/sec  |  Ctrl+C to stop\n")
        print(f"Start the app with:\n  LOG_DIR={args.dir} python3 run.py\n")

        weights = [60, 20, 10, 10]
        keys    = ['access', 'error', 'ssl_error', 'php_error']
        try:
            while True:
                kind = random.choices(keys, weights=weights)[0]
                if kind == 'access':
                    line = access_line()
                else:
                    line = error_line()
                files[kind].write(line + '\n')
                time.sleep(1.0 / args.rate)
        finally:
            for fh in files.values():
                fh.close()
    else:
        # Legacy single-file mode
        print(f"Writing access logs → {args.access}")
        print(f"Writing error  logs → {args.error}")
        print(f"Rate: {args.rate} lines/sec  |  Ctrl+C to stop\n")
        print("Start the app with:")
        print(f"  LOG_DIR=$(dirname {args.access}) python3 run.py\n")

        with open(args.access, 'a', buffering=1) as af, \
             open(args.error,  'a', buffering=1) as ef:
            while True:
                kind = random.choices(['access', 'error'], weights=[70, 30])[0]
                if kind == 'access':
                    af.write(access_line() + '\n')
                else:
                    ef.write(error_line() + '\n')
                time.sleep(1.0 / args.rate)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
        sys.exit(0)
