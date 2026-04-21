#!/usr/bin/env python3
"""
Deploy (or update) the trading-bot Lambda function and EventBridge schedule.

Prerequisites:
    - AWS CLI v2 installed and configured (`aws configure`)
    - IAM user/role with permissions to create Lambda, Scheduler, IAM roles, and CloudWatch logs
    - .env file with secrets present in project root

Usage:
    python scripts/deploy_lambda.py

Environment overrides:
    AWS_REGION           default: ap-southeast-1
    AWS_PROFILE          default: default
    LAMBDA_FUNCTION_NAME default: airdrop-trading-bot
    LAMBDA_MEMORY        default: 512
    LAMBDA_TIMEOUT       default: 300  (seconds)
    SCHEDULE_NAME        default: airdrop-trading-bot-hourly
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
ZIP_FILE = PROJECT_ROOT / "lambda_deployment.zip"
ENV_FILE = PROJECT_ROOT / ".env"

AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
AWS_PROFILE = os.environ.get("AWS_PROFILE", "default")
FUNCTION_NAME = os.environ.get("LAMBDA_FUNCTION_NAME", "airdrop-trading-bot")
MEMORY = int(os.environ.get("LAMBDA_MEMORY", "512"))
TIMEOUT = int(os.environ.get("LAMBDA_TIMEOUT", "300"))
SCHEDULE_NAME = os.environ.get("SCHEDULE_NAME", "airdrop-trading-bot-hourly")
RUNTIME = "python3.12"
HANDLER = "src.lambda_handler.handler"

ROLE_NAME = f"{FUNCTION_NAME}-execution-role"
SCHEDULER_ROLE_NAME = f"{FUNCTION_NAME}-scheduler-role"


def aws_cli(cmd: list[str], capture: bool = False) -> str:
    """Run an AWS CLI command. Uses --profile in local dev, env vars in CI."""
    # In GitHub Actions, AWS credentials come from env vars, not a profile
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("AWS_ACCESS_KEY_ID"):
        base = ["aws", "--region", AWS_REGION]
    else:
        base = ["aws", "--profile", AWS_PROFILE, "--region", AWS_REGION]
    full = base + cmd
    print(f"$ aws ... {' '.join(cmd)}")
    if capture:
        result = subprocess.run(full, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    subprocess.check_call(full)
    return ""


def load_env() -> dict[str, str]:
    """Read .env and return a dict of key=value pairs. Strips inline comments."""
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        print(f"WARNING: {ENV_FILE} not found. Lambda will have no env vars.")
        return env
    for raw_line in ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        # Strip inline comments
        if "#" in val:
            val = val.split("#", 1)[0]
        env[key] = val.strip()
    return env


def get_account_id() -> str:
    out = aws_cli(["sts", "get-caller-identity"], capture=True)
    return json.loads(out)["Account"]


def create_execution_role() -> str:
    """Create or fetch the Lambda execution role ARN."""
    try:
        out = aws_cli(
            ["iam", "get-role", "--role-name", ROLE_NAME],
            capture=True,
        )
        data = json.loads(out)
        arn = data["Role"]["Arn"]
        print(f"Role already exists: {arn}")
        return arn
    except subprocess.CalledProcessError:
        print(f"Creating IAM role: {ROLE_NAME}")
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        aws_cli(
            [
                "iam",
                "create-role",
                "--role-name",
                ROLE_NAME,
                "--assume-role-policy-document",
                json.dumps(trust_policy),
            ]
        )
        aws_cli(
            [
                "iam",
                "attach-role-policy",
                "--role-name",
                ROLE_NAME,
                "--policy-arn",
                "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            ]
        )
        time.sleep(5)
        out = aws_cli(
            ["iam", "get-role", "--role-name", ROLE_NAME],
            capture=True,
        )
        data = json.loads(out)
        return data["Role"]["Arn"]


def function_exists(name: str) -> bool:
    try:
        aws_cli(["lambda", "get-function", "--function-name", name], capture=True)
        return True
    except subprocess.CalledProcessError:
        return False


def create_or_update_lambda(role_arn: str) -> str:
    """Create new function or update existing one. Returns function ARN."""
    env_vars = load_env()
    env_json = json.dumps({"Variables": env_vars}) if env_vars else None

    if not ZIP_FILE.exists():
        print(f"ERROR: {ZIP_FILE} not found. Run scripts/build_lambda.py first.")
        sys.exit(1)

    if function_exists(FUNCTION_NAME):
        print(f"Updating existing Lambda: {FUNCTION_NAME}")
        aws_cli(
            [
                "lambda",
                "update-function-code",
                "--function-name",
                FUNCTION_NAME,
                "--zip-file",
                f"fileb://{ZIP_FILE}",
            ]
        )
        print("Waiting 10s for code update to settle...")
        time.sleep(10)
        update_cmd = [
            "lambda",
            "update-function-configuration",
            "--function-name",
            FUNCTION_NAME,
            "--handler",
            HANDLER,
            "--runtime",
            RUNTIME,
            "--memory-size",
            str(MEMORY),
            "--timeout",
            str(TIMEOUT),
        ]
        if env_json:
            update_cmd += ["--environment", env_json]
        else:
            print("No .env found — skipping env var update to preserve existing vars.")
        aws_cli(update_cmd)
    else:
        print(f"Creating new Lambda: {FUNCTION_NAME}")
        create_cmd = [
            "lambda",
            "create-function",
            "--function-name",
            FUNCTION_NAME,
            "--runtime",
            RUNTIME,
            "--role",
            role_arn,
            "--handler",
            HANDLER,
            "--memory-size",
            str(MEMORY),
            "--timeout",
            str(TIMEOUT),
            "--zip-file",
            f"fileb://{ZIP_FILE}",
        ]
        if env_json:
            create_cmd += ["--environment", env_json]
        aws_cli(create_cmd)

    out = aws_cli(
        ["lambda", "get-function", "--function-name", FUNCTION_NAME],
        capture=True,
    )
    data = json.loads(out)
    arn = data["Configuration"]["FunctionArn"]
    print(f"Lambda ARN: {arn}")
    return arn


def create_scheduler_role(function_arn: str) -> str:
    """Create or fetch the IAM role that EventBridge Scheduler uses to invoke Lambda."""
    try:
        out = aws_cli(
            ["iam", "get-role", "--role-name", SCHEDULER_ROLE_NAME],
            capture=True,
        )
        data = json.loads(out)
        arn = data["Role"]["Arn"]
        print(f"Scheduler role already exists: {arn}")
        return arn
    except subprocess.CalledProcessError:
        print(f"Creating scheduler role: {SCHEDULER_ROLE_NAME}")
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "scheduler.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        aws_cli(
            [
                "iam",
                "create-role",
                "--role-name",
                SCHEDULER_ROLE_NAME,
                "--assume-role-policy-document",
                json.dumps(trust_policy),
            ]
        )
        # Attach inline policy to allow invoking this specific Lambda
        invoke_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "lambda:InvokeFunction",
                    "Resource": function_arn,
                }
            ],
        }
        aws_cli(
            [
                "iam",
                "put-role-policy",
                "--role-name",
                SCHEDULER_ROLE_NAME,
                "--policy-name",
                "InvokeLambda",
                "--policy-document",
                json.dumps(invoke_policy),
            ]
        )
        time.sleep(5)
        out = aws_cli(
            ["iam", "get-role", "--role-name", SCHEDULER_ROLE_NAME],
            capture=True,
        )
        data = json.loads(out)
        return data["Role"]["Arn"]


def create_or_update_schedule(function_arn: str) -> None:
    """Create or update the EventBridge schedule to invoke Lambda every hour."""
    schedule_group = "default"
    account_id = get_account_id()
    scheduler_role_arn = create_scheduler_role(function_arn)
    target = {
        "RoleArn": scheduler_role_arn,
        "Arn": function_arn,
        "Input": json.dumps({"source": "eventbridge-scheduler"}),
    }

    try:
        aws_cli(
            [
                "scheduler",
                "get-schedule",
                "--name",
                SCHEDULE_NAME,
                "--group-name",
                schedule_group,
            ],
            capture=True,
        )
        print(f"Updating schedule: {SCHEDULE_NAME}")
        aws_cli(
            [
                "scheduler",
                "update-schedule",
                "--name",
                SCHEDULE_NAME,
                "--group-name",
                schedule_group,
                "--schedule-expression",
                "rate(1 hour)",
                "--target",
                json.dumps(target),
                "--flexible-time-window",
                '{"Mode": "OFF"}',
            ]
        )
    except subprocess.CalledProcessError:
        print(f"Creating schedule: {SCHEDULE_NAME}")
        aws_cli(
            [
                "scheduler",
                "create-schedule",
                "--name",
                SCHEDULE_NAME,
                "--group-name",
                schedule_group,
                "--schedule-expression",
                "rate(1 hour)",
                "--target",
                json.dumps(target),
                "--flexible-time-window",
                '{"Mode": "OFF"}',
            ]
        )

    try:
        aws_cli(
            [
                "lambda",
                "add-permission",
                "--function-name",
                FUNCTION_NAME,
                "--statement-id",
                "EventBridgeSchedulerInvoke",
                "--action",
                "lambda:InvokeFunction",
                "--principal",
                "scheduler.amazonaws.com",
                "--source-arn",
                f"arn:aws:scheduler:{AWS_REGION}:{account_id}:schedule/{schedule_group}/{SCHEDULE_NAME}",
            ]
        )
    except subprocess.CalledProcessError:
        print("Permission already exists (or failed silently).")


def main() -> None:
    # Skip configure check in CI — credentials come from env vars
    if not os.environ.get("GITHUB_ACTIONS"):
        try:
            aws_cli(["sts", "get-caller-identity"], capture=True)
        except subprocess.CalledProcessError:
            print(
                "ERROR: AWS CLI is not configured. Run 'aws configure' first.\n"
                "See LAMBDA_SETUP.md for detailed instructions."
            )
            sys.exit(1)

    role_arn = create_execution_role()
    function_arn = create_or_update_lambda(role_arn)
    create_or_update_schedule(function_arn)

    print("\n✅ Deployment complete!")
    print(f"   Lambda:  https://{AWS_REGION}.console.aws.amazon.com/lambda/home?region={AWS_REGION}#/functions/{FUNCTION_NAME}")
    print(f"   Logs:    https://{AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region={AWS_REGION}#logsV2:log-groups/log-group/$252Faws$252Flambda$252F{FUNCTION_NAME}")


if __name__ == "__main__":
    main()
