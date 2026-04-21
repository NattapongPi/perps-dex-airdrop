# Lambda + EventBridge Setup Guide

This guide assumes you know **nothing** about AWS Lambda. Follow step by step.

---

## What we are building

- **AWS Lambda** — runs your trading bot code on-demand (no server running 24/7)
- **EventBridge Scheduler** — triggers Lambda once every hour
- **CloudWatch Logs** — automatically captures all logs (no config needed)

**Cost:** ~$0.50–2/month instead of ~$15–20/month for ECS Fargate.

---

## Step 1: Install AWS CLI

1. Download AWS CLI v2: https://aws.amazon.com/cli/
2. Install it, then open a terminal and run:

```bash
aws --version
```

You should see something like `aws-cli/2.x.x`.

---

## Step 2: Configure AWS credentials

You need an **Access Key ID** and **Secret Access Key** from AWS.

### If you don't have them:
1. Log into AWS Console → IAM → Users → your user
2. Go to **Security credentials** tab
3. Click **Create access key**
4. Save both values (you can't see the secret again)

### Configure locally:
```bash
aws configure
```
Enter:
- AWS Access Key ID: `your-key`
- AWS Secret Access Key: `your-secret`
- Default region name: `ap-southeast-1` (or your region)
- Default output format: `json`

Test it:
```bash
aws sts get-caller-identity
```
If you see your account info, it works.

---

## Step 3: Create the Lambda execution role (one-time)

Lambda needs permission to write logs. We create an IAM role for it.

The deploy script (`scripts/deploy_lambda.py`) does this automatically on first run. **You can skip this step** — just run the deploy script and it will create the role for you.

If you prefer to do it manually in the console:
1. IAM → Roles → Create role
2. Trusted entity: **AWS Service** → **Lambda**
3. Attach policy: `AWSLambdaBasicExecutionRole`
4. Role name: `airdrop-trading-bot-execution-role`

---

## Step 4: Prepare your .env file

Make sure your `.env` file in the project root has your secrets. The deploy script reads from it and injects them into Lambda as encrypted environment variables.

Example `.env`:
```bash
HYPERLIQUID_WALLET_ADDRESS=0x...
HYPERLIQUID_PRIVATE_KEY=0x...
HIBACHI_API_KEY=...
HIBACHI_ACCOUNT_ID=...
HIBACHI_PRIVATE_KEY=...
```

**Important:** `.env` is in `.gitignore` — it will never be committed to GitHub. The deploy script sends it directly to AWS, not to git.

---

## Step 5: Deploy

Run these two commands from the project root:

```bash
# 1. Build the deployment zip
python scripts/build_lambda.py

# 2. Deploy to AWS (creates Lambda + EventBridge schedule)
python scripts/deploy_lambda.py
```

The first deploy will:
- Create the IAM execution role
- Create the Lambda function
- Create the EventBridge schedule (every hour)
- Set your `.env` secrets as Lambda environment variables

Subsequent deploys just update the code.

---

## Step 6: Verify it's working

### In the AWS Console:
1. Go to https://ap-southeast-1.console.aws.amazon.com/lambda/home
2. Click `airdrop-trading-bot`
3. Click the **Test** tab → **Test** button
4. Check the **Logs** tab or go to CloudWatch Logs

### In CloudWatch Logs:
1. https://ap-southeast-1.console.aws.amazon.com/cloudwatch/home → Logs → Log groups
2. Find `/aws/lambda/airdrop-trading-bot`
3. Click the latest log stream to see your bot's output

### Check the schedule:
1. https://ap-southeast-1.console.aws.amazon.com/eventbridge/home → Scheduler → Schedules
2. You should see `airdrop-trading-bot-hourly` with expression `rate(1 hour)`

---

## Step 7: Monitor costs

1. Go to https://console.aws.amazon.com/billing/home
2. Lambda pricing: ~$0.20 per 1 million requests + $0.0000166667 per GB-second
3. For your bot (512 MB, ~30 seconds, once/hour): roughly **$0.50–1/month**

---

## Common issues

### "AWS CLI is not configured"
Run `aws configure` and enter your credentials.

### "Permission denied" during deploy
Your IAM user needs these permissions:
- `lambda:CreateFunction`, `lambda:UpdateFunctionCode`, `lambda:UpdateFunctionConfiguration`
- `scheduler:CreateSchedule`, `scheduler:UpdateSchedule`
- `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:GetRole`, `iam:PassRole`
- `logs:CreateLogGroup`

### Lambda timeout
If your bot takes longer than 5 minutes, increase timeout:
```bash
aws lambda update-function-configuration --function-name airdrop-trading-bot --timeout 600
```

### Want to stop the schedule?
```bash
aws scheduler delete-schedule --name airdrop-trading-bot-hourly
```

---

## Rollback to ECS

Your ECS setup is untouched. To go back:
1. Stop/delete the Lambda schedule (or delete the Lambda function)
2. Re-deploy ECS using your old GitHub Actions workflow
3. The old `task-definition.json` and Docker setup still work
