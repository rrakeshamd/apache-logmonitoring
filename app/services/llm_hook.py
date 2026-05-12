"""
LLM integration hook — disabled by default.

To enable:
  1. Set LLM_ENABLED=true in .env
  2. Set AMD_SUBSCRIPTION_KEY=<your-key> in .env
  3. pip install openai

The /api/analyze route checks LLM_ENABLED before calling this module.
"""

import os
import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an expert Apache web server log analysis tool. \
Your job is to analyze log entries and provide clear, structured diagnostics with actionable suggestions.

When given log lines, always respond in this exact format:

## Summary
One or two sentences describing the overall state of the logs.

## Issues Found
List each problem detected (errors, warnings, anomalies, suspicious activity, \
high response times, 4xx/5xx spikes). For each issue:
- **Issue:** What was observed
- **Severity:** Critical / High / Medium / Low
- **Suggestion:** What the operator should do to fix or investigate it

## Security Alerts
Call out any suspicious patterns: repeated 404s, scanning behavior, unusual user agents, \
brute-force attempts, unexpected IP addresses. If none, write "None detected."

## Performance Notes
Flag slow requests (high response time or large payload), repeated heavy endpoints, or \
traffic spikes. If none, write "None detected."

## Recommended Actions
A numbered list of the most important next steps the operator should take, in priority order.

Be concise. Skip sections that have nothing to report rather than writing filler."""


def analyze_with_llm(log_lines: list, subscription_key: str, model: str) -> dict:
    """
    Send log lines to the AMD internal LLM API and return the analysis as a dict.

    Raises ValueError on bad credentials or API errors.
    """
    if not subscription_key:
        raise ValueError("AMD_SUBSCRIPTION_KEY is not set.")

    client = OpenAI(
        base_url="https://llm-api.amd.com/OnPrem",
        api_key="dummy",
        default_headers={
            "Ocp-Apim-Subscription-Key": subscription_key,
            "user": os.getlogin(),
        },
    )

    chunk_text = "\n".join(log_lines)
    try:
        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=1024,
            temperature=0.7,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Analyze these Apache log entries and provide diagnostics with suggestions:\n\n```\n{chunk_text}\n```"},
            ],
        )
    except Exception as e:
        raise ValueError(str(e)) from e

    return {
        "success":        True,
        "analysis":       response.choices[0].message.content,
        "model":          model,
        "lines_analyzed": len(log_lines),
    }
