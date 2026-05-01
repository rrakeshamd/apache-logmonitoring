"""
LLM integration hook — disabled by default.

To enable:
  1. Set LLM_ENABLED=true in .env
  2. Set ANTHROPIC_API_KEY=sk-ant-... in .env
  3. Optionally: pip install anthropic  (urllib fallback works without it)

The /api/analyze route checks LLM_ENABLED before calling this module.
"""

import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an Apache web server log analyst. "
    "The user will send you a chunk of Apache access or error log lines. "
    "Identify patterns, anomalies, errors, suspicious requests, or performance issues. "
    "Be concise. Use bullet points. Focus on actionable observations."
)


def analyze_with_claude(log_lines: list, api_key: str, model: str) -> dict:
    """
    Send log lines to Claude and return the analysis as a dict.
    Uses anthropic SDK if installed, falls back to urllib (no extra deps required).

    Raises ValueError on bad credentials or API errors.
    """
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set.")

    chunk_text = "\n".join(log_lines)
    user_message = f"Analyze these Apache log entries:\n\n```\n{chunk_text}\n```"

    # Try the anthropic SDK first (cleaner error messages)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return {
            'success':        True,
            'analysis':       response.content[0].text,
            'model':          model,
            'lines_analyzed': len(log_lines),
        }
    except ImportError:
        pass  # Fall through to urllib approach

    # Stdlib urllib fallback
    payload = json.dumps({
        "model":      model,
        "max_tokens": 1024,
        "system":     _SYSTEM_PROMPT,
        "messages":   [{"role": "user", "content": user_message}],
    }).encode()

    req = urllib.request.Request(
        url='https://api.anthropic.com/v1/messages',
        data=payload,
        headers={
            'x-api-key':         api_key,
            'anthropic-version': '2023-06-01',
            'content-type':      'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return {
            'success':        True,
            'analysis':       data['content'][0]['text'],
            'model':          model,
            'lines_analyzed': len(log_lines),
        }
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')
        raise ValueError(f"Anthropic API error {e.code}: {body}") from e
