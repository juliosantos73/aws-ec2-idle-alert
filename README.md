# aws-ec2-idle-alert

🌐 [English](README.md) | [Português](README.pt-BR.md)

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-orange?logo=amazon-aws)

An AWS Lambda function that **detects idle EC2 instances** by querying CloudWatch CPU metrics and sends alerts via SNS. Runs daily across all regions via EventBridge.

---

## How it works

```
EventBridge (daily cron) ──► Lambda ──► describe_instances (running, all regions)
                                    │       └── get_metric_statistics (CPUUtilization, last N hours)
                                    │               └── avg CPU < CPU_THRESHOLD → idle
                                    │
                                    └── (if idle instances found)
                                            └──► SNS Topic ──► Email
```

---

## Features

- Checks **all running EC2 instances across all regions**
- Configurable **CPU threshold** and **observation window** (hours)
- Includes instance `Name` tag in the alert for easy identification
- Skips instances with no CloudWatch data (e.g., recently launched)
- Per-instance error handling — one failure does not stop the region
- Structured JSON logs — compatible with CloudWatch Insights
- Dry run mode — lists idle instances without sending notifications
- Adaptive retry — handles AWS API throttling automatically

---

## Prerequisites

- An AWS account
- EC2 instances must have **CloudWatch detailed monitoring** enabled (optional) or standard monitoring (data every 5 minutes)
- Python 3.12+ (for local development only)
- AWS CLI configured (optional)

> **Note:** CloudWatch metric data has a delay of up to 5 minutes for standard monitoring. The Lambda queries the last `IDLE_HOURS` of data, so very recent activity may not be reflected.

---

## 1. Create the SNS topic

```bash
TOPIC_ARN=$(aws sns create-topic --name ec2-idle-alert --query TopicArn --output text)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint your@email.com
echo "Topic ARN: $TOPIC_ARN"
```

---

## 2. Create the IAM execution role

**Policy document** — save as `ec2-idle-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeRegions",
        "ec2:DescribeInstances",
        "cloudwatch:GetMetricStatistics"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["sns:Publish"],
      "Resource": "<your-sns-topic-arn>"
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

```bash
aws iam create-role --role-name ec2-idle-role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

aws iam put-role-policy --role-name ec2-idle-role \
  --policy-name ec2-idle-policy --policy-document file://ec2-idle-policy.json
```

---

## 3. Deploy the Lambda function

```bash
zip lambda_function.zip lambda_function.py
ROLE_ARN=$(aws iam get-role --role-name ec2-idle-role --query Role.Arn --output text)

aws lambda create-function \
  --function-name ec2-idle-alert \
  --runtime python3.12 --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda_function.zip --timeout 300
```

---

## 4. Configure the EventBridge rule

```bash
LAMBDA_ARN=$(aws lambda get-function --function-name ec2-idle-alert --query Configuration.FunctionArn --output text)

aws events put-rule --name EC2IdleAlert \
  --schedule-expression "cron(0 9 * * ? *)" --state ENABLED

aws events put-targets --rule EC2IdleAlert --targets "Id=1,Arn=$LAMBDA_ARN"

aws lambda add-permission --function-name ec2-idle-alert \
  --statement-id AllowEventBridge --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn $(aws events describe-rule --name EC2IdleAlert --query RuleArn --output text)
```

---

## Configuration

| Variable         | Default | Description                                                     |
|------------------|---------|-----------------------------------------------------------------|
| `CPU_THRESHOLD`  | `5.0`   | Average CPU % below which an instance is considered idle        |
| `IDLE_HOURS`     | `24`    | Observation window in hours for the CPU average                 |
| `SNS_TOPIC_ARN`  | _(none)_| SNS topic ARN for email notifications                           |
| `DRY_RUN`        | `false` | Set to `true` to log findings without sending notifications     |

```bash
aws lambda update-function-configuration \
  --function-name ec2-idle-alert \
  --environment "Variables={CPU_THRESHOLD=5.0,IDLE_HOURS=24,SNS_TOPIC_ARN=arn:aws:sns:...}"
```

---

## Testing

```bash
aws lambda invoke \
  --function-name ec2-idle-alert \
  --payload '{"dry_run":true}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json
```

---

## Example response

```json
{
  "result": "alert",
  "dry_run": false,
  "idle_instances": [
    {
      "instance_id": "i-0abc123def456",
      "name": "staging-worker",
      "region": "us-east-1",
      "avg_cpu_percent": 0.42,
      "idle_hours": 24
    }
  ]
}
```

---

## Monitoring

```
fields @timestamp, region, instance_id, name, avg_cpu
| filter ispresent(avg_cpu)
| sort avg_cpu asc
| limit 20
```

---

## Local development

```bash
pip install -r requirements-dev.txt
python -c "from lambda_function import lambda_handler; print(lambda_handler({'dry_run': True}, None))"
```

---

## Contributing

1. Fork the repository
2. Create a branch: `git checkout -b feature/your-feature`
3. Commit and push, then open a Pull Request

---

## License

[MIT](LICENSE) — © Júlio César Santos
