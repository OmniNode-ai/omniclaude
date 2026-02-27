# _lib/slack-gate/helpers.md

**Shared Slack gate posting and polling helpers.**

Extracted from merge-sweep and slack-gate skills for reuse by integration-gate,
release, and other skills that need human-in-the-loop approval.

## Import

```
@_lib/slack-gate/helpers.md
```

---

## Constants

```python
import os

# Credential resolution (from ~/.omnibase/.env or Infisical)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# Default timeouts by risk tier (minutes)
GATE_TIMEOUTS = {
    "LOW_RISK": 30,
    "MEDIUM_RISK": 60,
    "HIGH_RISK": 1440,  # 24 hours
}

# Default poll intervals by risk tier (seconds)
GATE_POLL_INTERVALS = {
    "LOW_RISK": 0,     # No polling -- auto-approve
    "MEDIUM_RISK": 60,
    "HIGH_RISK": 60,
}

# Default keyword sets
ACCEPT_KEYWORDS = ["yes", "proceed", "merge", "approve"]
REJECT_KEYWORDS = ["no", "reject", "cancel", "hold", "deny"]
```

---

## resolve_credentials()

Load Slack credentials from ~/.omnibase/.env, falling back to environment.

```python
import subprocess


def resolve_credentials() -> tuple[str, str]:
    """Resolve Slack Bot Token and Channel ID.

    Resolution order:
    1. Source ~/.omnibase/.env
    2. Check environment variables
    3. Fail if neither available

    Returns:
        (bot_token, channel_id) tuple.

    Raises:
        RuntimeError: If credentials are not available.
    """
    # Source ~/.omnibase/.env if it exists
    env_path = os.path.expanduser("~/.omnibase/.env")
    if os.path.exists(env_path):
        # Parse .env file manually (no dotenv dependency)
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key == "SLACK_BOT_TOKEN" and value:
                        os.environ.setdefault("SLACK_BOT_TOKEN", value)
                    elif key == "SLACK_CHANNEL_ID" and value:
                        os.environ.setdefault("SLACK_CHANNEL_ID", value)

    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel_id = os.environ.get("SLACK_CHANNEL_ID", "")

    if not bot_token or not channel_id:
        raise RuntimeError(
            "Slack credentials not available. "
            "Set SLACK_BOT_TOKEN and SLACK_CHANNEL_ID in ~/.omnibase/.env"
        )

    return bot_token, channel_id
```

---

## post_gate(risk_level, message, timeout_minutes)

Post a gate message to Slack and return the thread timestamp.

```python
import json
import urllib.request
import urllib.error


def post_gate(
    risk_level: str,
    message: str,
    timeout_minutes: int | None = None,
) -> str | None:
    """Post a risk-tiered gate message to Slack via chat.postMessage.

    Args:
        risk_level: Gate tier: LOW_RISK | MEDIUM_RISK | HIGH_RISK
        message: Gate message body (Markdown).
        timeout_minutes: Override default timeout for this tier.

    Returns:
        thread_ts (str) if posted via Bot Token, None if webhook fallback.

    Raises:
        RuntimeError: If both Bot Token and webhook are unavailable.
    """
    timeout = timeout_minutes or GATE_TIMEOUTS.get(risk_level, 60)

    # Silence note by tier
    silence_notes = {
        "LOW_RISK": "No reply needed -- silence = consent.",
        "MEDIUM_RISK": f"Silence escalates after {timeout} minutes.",
        "HIGH_RISK": "Explicit approval required -- silence holds.",
    }
    silence_note = silence_notes.get(risk_level, "")

    formatted = (
        f"*[{risk_level}]* integration-gate:\n\n"
        f"{message}\n\n"
        f"Reply \"proceed\" to approve. {silence_note}\n"
        f"Gate expires in {timeout} minutes."
    )

    try:
        bot_token, channel_id = resolve_credentials()
    except RuntimeError:
        # Webhook fallback (LOW_RISK only)
        if risk_level == "LOW_RISK" and SLACK_WEBHOOK_URL:
            _post_webhook(formatted)
            return None
        raise

    # Post via chat.postMessage
    payload = json.dumps({
        "channel": channel_id,
        "text": formatted,
    }).encode()

    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if not data.get("ok"):
                raise RuntimeError(f"chat.postMessage failed: {data.get('error')}")
            return data["message"]["ts"]
    except urllib.error.URLError as exc:
        # Webhook fallback for LOW_RISK
        if risk_level == "LOW_RISK" and SLACK_WEBHOOK_URL:
            _post_webhook(formatted)
            return None
        raise RuntimeError(f"Failed to post gate message: {exc}") from exc


def _post_webhook(message: str) -> None:
    """Fire-and-forget webhook post (no thread_ts capture)."""
    payload = json.dumps({"text": message}).encode()
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10)
```

---

## poll_gate_reply(thread_ts, timeout_minutes, poll_interval_seconds)

Poll a Slack thread for a human reply.

```python
import time


class GateResult:
    """Result of a gate poll."""
    def __init__(self, status: str, reply: str | None = None):
        self.status = status    # "accepted" | "rejected" | "timeout"
        self.reply = reply


def poll_gate_reply(
    thread_ts: str | None,
    risk_level: str = "HIGH_RISK",
    timeout_minutes: int | None = None,
    poll_interval_seconds: int | None = None,
    accept_keywords: list[str] | None = None,
    reject_keywords: list[str] | None = None,
) -> GateResult:
    """Poll a Slack thread for a human reply.

    LOW_RISK gates skip polling entirely and auto-approve.

    Args:
        thread_ts: Thread timestamp from post_gate(). None for webhook fallback.
        risk_level: Gate tier for default timeout/interval.
        timeout_minutes: Override default timeout.
        poll_interval_seconds: Override default poll interval.
        accept_keywords: Override default accept keywords.
        reject_keywords: Override default reject keywords.

    Returns:
        GateResult with status and matched reply text.
    """
    # LOW_RISK: auto-approve, no polling
    if risk_level == "LOW_RISK":
        return GateResult(status="accepted", reply=None)

    # No thread_ts means webhook fallback -- cannot poll
    if thread_ts is None:
        return GateResult(status="timeout", reply=None)

    timeout = (timeout_minutes or GATE_TIMEOUTS.get(risk_level, 60)) * 60
    interval = poll_interval_seconds or GATE_POLL_INTERVALS.get(risk_level, 60)
    accept = accept_keywords or ACCEPT_KEYWORDS
    reject = reject_keywords or REJECT_KEYWORDS

    try:
        bot_token, channel_id = resolve_credentials()
    except RuntimeError:
        return GateResult(status="timeout", reply=None)

    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(interval)

        # Fetch replies
        try:
            params = (
                f"channel={channel_id}"
                f"&ts={thread_ts}"
                f"&oldest={thread_ts}"
                f"&limit=100"
            )
            req = urllib.request.Request(
                f"https://slack.com/api/conversations.replies?{params}",
                headers={"Authorization": f"Bearer {bot_token}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                if not data.get("ok"):
                    continue

                messages = data.get("messages", [])
                # Skip the original gate message (first message)
                for msg in messages[1:]:
                    text = msg.get("text", "").lower().strip()
                    if any(kw in text for kw in accept):
                        return GateResult(status="accepted", reply=text)
                    if any(kw in text for kw in reject):
                        return GateResult(status="rejected", reply=text)

        except (urllib.error.URLError, json.JSONDecodeError):
            continue

    return GateResult(status="timeout", reply=None)
```

---

## validate_gate_attestation(token, expected_run_id, expected_plan_hash)

Validate a pre-issued gate attestation token.

```python
import re

ATTESTATION_PATTERN = re.compile(
    r"^(?P<run_id>[^:]+):(?P<plan_hash>[a-f0-9]{64}):(?P<slack_ts>[0-9]{10}\.[0-9]{6})$"
)


def validate_gate_attestation(
    token: str,
    expected_run_id: str,
    expected_plan_hash: str,
) -> bool:
    """Validate a gate attestation token.

    Token format: <run_id>:<plan_hash>:<slack_ts>

    Validates:
    1. Token format matches expected pattern
    2. run_id in token matches expected_run_id
    3. plan_hash in token matches expected_plan_hash (current plan state)

    Args:
        token: The gate attestation token.
        expected_run_id: The current run ID.
        expected_plan_hash: SHA-256 of the current normalized plan.

    Returns:
        True if valid.

    Raises:
        ValueError: If token format is invalid or fields do not match.
    """
    match = ATTESTATION_PATTERN.match(token)
    if not match:
        raise ValueError(
            f"Invalid gate attestation format: '{token}'. "
            f"Expected: <run_id>:<plan_hash>:<slack_ts>"
        )

    token_run_id = match.group("run_id")
    token_plan_hash = match.group("plan_hash")

    if token_run_id != expected_run_id:
        raise ValueError(
            f"Gate attestation run_id mismatch: "
            f"token='{token_run_id}', expected='{expected_run_id}'"
        )

    if token_plan_hash != expected_plan_hash:
        raise ValueError(
            f"GATE_PLAN_DRIFT: plan_hash mismatch. "
            f"token='{token_plan_hash[:12]}...', "
            f"expected='{expected_plan_hash[:12]}...'. "
            f"The plan has changed since the gate was approved."
        )

    return True
```

---

## post_to_thread(thread_ts, message)

Post a follow-up message to an existing Slack thread.

```python
def post_to_thread(thread_ts: str, message: str) -> None:
    """Post a follow-up message to a Slack thread.

    Best-effort: logs warning on failure, does not raise.

    Args:
        thread_ts: Thread timestamp to reply to.
        message: Message text.
    """
    try:
        bot_token, channel_id = resolve_credentials()
    except RuntimeError:
        return

    payload = json.dumps({
        "channel": channel_id,
        "thread_ts": thread_ts,
        "text": message,
    }).encode()

    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.URLError:
        pass  # Best-effort
```

---

## Usage Pattern

```python
# In integration-gate prompt.md:

# Post gate
thread_ts = post_gate(
    risk_level="HIGH_RISK",
    message=plan_table_formatted,
)

# Poll for approval
result = poll_gate_reply(
    thread_ts=thread_ts,
    risk_level="HIGH_RISK",
    timeout_minutes=60,
)

if result.status == "rejected":
    emit ModelSkillResult(status="gate_rejected")
    exit

# On ejection, post to thread:
post_to_thread(
    thread_ts=thread_ts,
    message=f"[EJECTION] {repo}#{pr_number} ejected: {reason}",
)

# Validate pre-issued attestation:
try:
    validate_gate_attestation(token, run_id, plan_hash)
except ValueError as e:
    emit ModelSkillResult(status="error", error=str(e))
    exit
```
