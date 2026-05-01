import re

# Apache Combined Log Format
_ACCESS_RE = re.compile(
    r'(?P<host>\S+)\s+\S+\s+(?P<user>\S+)\s+'
    r'\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)'
    r'(?:\s+"(?P<referer>[^"]*)")?'
    r'(?:\s+"(?P<useragent>[^"]*)")?'
)

# Apache Error Log Format
_ERROR_RE = re.compile(
    r'\[(?P<time>[^\]]+)\]\s+'
    r'\[(?P<module>[^\]]*):(?P<level>[^\]]+)\]\s+'
    r'\[pid\s+[^\]]+\]\s+'
    r'(?P<message>.+)'
)

_ERROR_KEYWORDS = {'error', 'crit', 'alert', 'emerg'}
_WARN_KEYWORDS  = {'warn', 'notice'}


def parse_access_line(raw: str) -> dict:
    m = _ACCESS_RE.match(raw)
    if not m:
        return {'raw': raw, 'type': 'access', 'level': 'info', 'status': None}
    status = int(m.group('status'))
    if status >= 500:
        level = 'error'
    elif status >= 400:
        level = 'warn'
    else:
        level = 'info'
    return {
        'type':      'access',
        'raw':       raw,
        'host':      m.group('host'),
        'user':      m.group('user'),
        'time':      m.group('time'),
        'method':    m.group('method'),
        'path':      m.group('path'),
        'status':    status,
        'size':      m.group('size'),
        'referer':   m.group('referer') or '',
        'useragent': m.group('useragent') or '',
        'level':     level,
    }


def parse_error_line(raw: str) -> dict:
    m = _ERROR_RE.match(raw)
    if not m:
        return {'raw': raw, 'type': 'error_log', 'level': 'error', 'status': None}
    level_str = m.group('level').lower()
    if any(k in level_str for k in _ERROR_KEYWORDS):
        level = 'error'
    elif any(k in level_str for k in _WARN_KEYWORDS):
        level = 'warn'
    else:
        level = 'info'
    return {
        'type':    'error_log',
        'raw':     raw,
        'time':    m.group('time'),
        'module':  m.group('module'),
        'level':   level,
        'message': m.group('message'),
        'status':  None,
    }
