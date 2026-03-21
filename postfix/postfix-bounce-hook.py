#!/usr/bin/env python3
"""
Postfix Bounce Hook

Parses Postfix mail.log for bounce notifications and forwards them to:
1. Bounce Bridge API
2. Mattermost webhook (preserving existing behavior)

Can be run via cron or as a log watcher.

Usage:
    # Process recent bounces from mail.log
    ./postfix-bounce-hook.py

    # Watch mail.log in real-time
    ./postfix-bounce-hook.py --watch

Configuration via environment variables:
    BOUNCE_BRIDGE_URL - Bounce Bridge API URL (default: http://192.168.103.176:8000)
    MATTERMOST_WEBHOOK_URL - Mattermost webhook URL (optional, preserves existing behavior)
"""

import os
import re
import sys
import json
import argparse
import subprocess
from datetime import datetime
from typing import Optional, Dict
import urllib.request
import urllib.error

# Configuration
BOUNCE_BRIDGE_URL = os.environ.get("BOUNCE_BRIDGE_URL", "http://192.168.103.176:8000")
MATTERMOST_WEBHOOK_URL = os.environ.get("MATTERMOST_WEBHOOK_URL", "")
MAIL_LOG = "/var/log/mail.log"
STATE_FILE = "/var/tmp/postfix-bounce-hook.state"

# Regex patterns for parsing mail.log
BOUNCE_PATTERN = re.compile(
    r'(?P<timestamp>\w+\s+\d+\s+\d+:\d+:\d+)\s+'
    r'(?P<host>\S+)\s+postfix/\S+\[\d+\]:\s+'
    r'(?P<queue_id>[A-F0-9]+):\s+'
    r'to=<(?P<to>[^>]+)>,\s+'
    r'.*?status=(?P<status>bounced|deferred|sent)\s+'
    r'\((?P<reason>.*?)\)'
)

DSN_PATTERN = re.compile(r'(\d\.\d\.\d)')


def parse_dsn(reason: str) -> str:
    """Extract DSN code from bounce reason."""
    match = DSN_PATTERN.search(reason)
    if match:
        return match.group(1)
    # Infer from common patterns
    if "user unknown" in reason.lower() or "does not exist" in reason.lower():
        return "5.1.1"
    if "mailbox full" in reason.lower():
        return "4.2.2"
    if "rejected" in reason.lower():
        return "5.7.1"
    return "5.0.0"


def get_sender_for_queue_id(queue_id: str) -> Optional[str]:
    """Try to find the sender for a queue ID from mail.log."""
    try:
        result = subprocess.run(
            ["grep", f"{queue_id}:", MAIL_LOG],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.split("\n"):
            if "from=<" in line:
                match = re.search(r'from=<([^>]*)>', line)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return None


def get_subject_for_queue_id(queue_id: str) -> Optional[str]:
    """Try to extract subject from message headers (if logged)."""
    # Postfix doesn't log subjects by default
    return None


def send_to_bounce_bridge(bounce_data: Dict) -> bool:
    """Send bounce notification to Bounce Bridge API."""
    url = f"{BOUNCE_BRIDGE_URL}/api/v1/postfix-bounce"

    try:
        data = json.dumps(bounce_data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except urllib.error.URLError as e:
        print(f"Failed to send to Bounce Bridge: {e}", file=sys.stderr)
        return False


def send_to_mattermost(bounce_data: Dict) -> bool:
    """Send bounce notification to Mattermost (preserving existing behavior)."""
    if not MATTERMOST_WEBHOOK_URL:
        return True  # Skip if not configured

    message = f"""**Email Bounce Detected**
| Field | Value |
|-------|-------|
| Recipient | {bounce_data['to']} |
| Status | {bounce_data['status']} |
| DSN | {bounce_data['dsn']} |
| Reason | {bounce_data['reason'][:200]} |
| Time | {bounce_data['timestamp']} |
"""

    payload = {"text": message}

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            MATTERMOST_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except urllib.error.URLError as e:
        print(f"Failed to send to Mattermost: {e}", file=sys.stderr)
        return False


def get_last_position() -> int:
    """Get last processed position in mail.log."""
    try:
        with open(STATE_FILE, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def save_position(pos: int):
    """Save current position in mail.log."""
    with open(STATE_FILE, "w") as f:
        f.write(str(pos))


def process_log_line(line: str) -> Optional[Dict]:
    """Parse a log line and return bounce data if it's a bounce."""
    match = BOUNCE_PATTERN.search(line)
    if not match:
        return None

    status = match.group("status")
    if status not in ("bounced", "deferred"):
        return None

    queue_id = match.group("queue_id")
    recipient = match.group("to")
    reason = match.group("reason")
    timestamp = match.group("timestamp")

    # Get sender
    sender = get_sender_for_queue_id(queue_id)

    # Parse DSN
    dsn = parse_dsn(reason)

    # Convert timestamp to ISO format
    try:
        # Assuming current year
        year = datetime.now().year
        dt = datetime.strptime(f"{year} {timestamp}", "%Y %b %d %H:%M:%S")
        iso_timestamp = dt.isoformat() + "Z"
    except ValueError:
        iso_timestamp = datetime.now().isoformat() + "Z"

    return {
        "from": sender or "",
        "to": recipient,
        "subject": "",
        "dsn": dsn,
        "status": status,
        "reason": reason,
        "relay": "",
        "timestamp": iso_timestamp,
    }


def process_mail_log(watch: bool = False):
    """Process mail.log for bounces."""
    if watch:
        # Real-time watching mode
        print(f"Watching {MAIL_LOG} for bounces...")
        process = subprocess.Popen(
            ["tail", "-F", MAIL_LOG],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            for line in process.stdout:
                bounce = process_log_line(line)
                if bounce:
                    print(f"Bounce detected: {bounce['to']}")
                    send_to_bounce_bridge(bounce)
                    send_to_mattermost(bounce)
        except KeyboardInterrupt:
            process.terminate()
    else:
        # Batch mode - process new lines since last run
        last_pos = get_last_position()

        try:
            with open(MAIL_LOG, "r") as f:
                f.seek(last_pos)
                new_lines = f.readlines()
                current_pos = f.tell()
        except FileNotFoundError:
            print(f"Mail log not found: {MAIL_LOG}", file=sys.stderr)
            return

        bounces_found = 0
        for line in new_lines:
            bounce = process_log_line(line)
            if bounce:
                bounces_found += 1
                print(f"Processing bounce: {bounce['to']}")
                send_to_bounce_bridge(bounce)
                send_to_mattermost(bounce)

        save_position(current_pos)
        print(f"Processed {len(new_lines)} lines, found {bounces_found} bounces")


def main():
    parser = argparse.ArgumentParser(description="Postfix Bounce Hook")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mail.log in real-time instead of batch processing",
    )
    args = parser.parse_args()

    process_mail_log(watch=args.watch)


if __name__ == "__main__":
    main()
