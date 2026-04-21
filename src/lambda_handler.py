"""
AWS Lambda handler entry point.

Triggered by EventBridge Scheduler every hour.
Wraps the existing src.main.run() orchestrator.
"""

from __future__ import annotations

import json
import sys

from src.main import run


def handler(event: dict, context) -> dict:
    """
    Lambda handler invoked by EventBridge Scheduler.

    Parameters
    ----------
    event : dict
        Event payload from EventBridge (usually empty for scheduled rules).
    context : LambdaContext
        AWS Lambda runtime context (memory, timeout, request_id, etc.).

    Returns
    -------
    dict
        Standard API Gateway-style response (not required for Scheduler,
        but useful for manual testing in the Lambda console).
    """
    # Log runtime limits so we can spot timeout issues in CloudWatch
    print(
        json.dumps({
            "message": "Lambda invoked",
            "aws_request_id": context.aws_request_id,
            "memory_limit_mb": context.memory_limit_in_mb,
            "remaining_time_ms": context.get_remaining_time_in_millis(),
            "event": event,
        }),
        flush=True,
    )

    try:
        run()
    except Exception as exc:
        # Print the traceback to CloudWatch Logs, then re-raise so Lambda
        # marks the invocation as a failure (EventBridge will retry).
        print(f"Unhandled exception: {exc}", file=sys.stderr, flush=True)
        raise

    return {
        "statusCode": 200,
        "body": json.dumps({"status": "ok", "message": "Scan complete"}),
    }
