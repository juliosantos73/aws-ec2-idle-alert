import json
import logging
import os
import traceback
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
CPU_THRESHOLD = float(os.environ.get('CPU_THRESHOLD', '5.0'))
IDLE_HOURS = int(os.environ.get('IDLE_HOURS', '24'))
DRY_RUN = os.environ.get('DRY_RUN', 'false').lower() == 'true'

logger = logging.getLogger()
logger.setLevel(logging.INFO)
BOTO_CONFIG = Config(retries={'max_attempts': 3, 'mode': 'adaptive'})


def get_avg_cpu(cw_client, instance_id: str) -> float | None:
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=IDLE_HOURS)

    response = cw_client.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='CPUUtilization',
        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
        StartTime=start_time,
        EndTime=end_time,
        Period=3600,
        Statistics=['Average'],
    )
    datapoints = response.get('Datapoints', [])
    if not datapoints:
        return None
    return round(sum(d['Average'] for d in datapoints) / len(datapoints), 2)


def check_region(ec2_client, cw_client, region_name: str) -> list[dict]:
    paginator = ec2_client.get_paginator('describe_instances')
    idle = []

    for page in paginator.paginate(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
    ):
        for reservation in page['Reservations']:
            for instance in reservation['Instances']:
                instance_id = instance['InstanceId']
                try:
                    avg_cpu = get_avg_cpu(cw_client, instance_id)
                    if avg_cpu is None or avg_cpu >= CPU_THRESHOLD:
                        continue

                    name = next(
                        (t['Value'] for t in instance.get('Tags', []) if t['Key'] == 'Name'),
                        instance_id,
                    )
                    idle.append({
                        'instance_id': instance_id,
                        'name': name,
                        'region': region_name,
                        'avg_cpu_percent': avg_cpu,
                        'idle_hours': IDLE_HOURS,
                    })
                    logger.info(json.dumps({
                        'region': region_name, 'instance_id': instance_id,
                        'name': name, 'avg_cpu': avg_cpu,
                    }))
                except Exception:
                    logger.error(json.dumps({
                        'region': region_name, 'instance_id': instance_id,
                        'error': traceback.format_exc(),
                    }))

    return idle


def build_message(idle_instances: list[dict]) -> str:
    lines = [
        f"EC2 Idle Instance Alert",
        f"",
        f"{len(idle_instances)} instance(s) with avg CPU < {CPU_THRESHOLD}% over the last {IDLE_HOURS}h:",
        "",
    ]
    for inst in idle_instances:
        lines.append(f"  {inst['region']} — {inst['name']} ({inst['instance_id']}): avg {inst['avg_cpu_percent']}% CPU")
    lines += ["", "Consider stopping or terminating these instances to reduce costs."]
    return '\n'.join(lines)


def lambda_handler(event: dict, context) -> dict:
    dry_run = bool(event.get('dry_run', DRY_RUN))
    logger.info(json.dumps({
        'dry_run': dry_run, 'cpu_threshold': CPU_THRESHOLD, 'idle_hours': IDLE_HOURS,
    }))

    ec2_global = boto3.client('ec2', config=BOTO_CONFIG)
    regions = ec2_global.describe_regions(
        Filters=[{'Name': 'opt-in-status', 'Values': ['opt-in-not-required', 'opted-in']}]
    )['Regions']

    all_idle = []
    start_time = datetime.now()

    for region in regions:
        region_name = region['RegionName']
        try:
            ec2 = boto3.client('ec2', region_name=region_name, config=BOTO_CONFIG)
            cw = boto3.client('cloudwatch', region_name=region_name, config=BOTO_CONFIG)
            all_idle.extend(check_region(ec2, cw, region_name))
        except Exception:
            logger.error(json.dumps({'region': region_name, 'error': traceback.format_exc()}))

    elapsed = round((datetime.now() - start_time).total_seconds(), 2)

    if not all_idle:
        logger.info(json.dumps({'result': 'no_idle_instances', 'elapsed_seconds': elapsed}))
        return {'statusCode': 200, 'body': json.dumps({'result': 'no_idle_instances'})}

    logger.info(json.dumps({'result': 'alert', 'count': len(all_idle), 'elapsed_seconds': elapsed}))

    if not dry_run and SNS_TOPIC_ARN:
        try:
            sns = boto3.client('sns', config=BOTO_CONFIG)
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f"EC2 Idle Alert — {len(all_idle)} instance(s) found",
                Message=build_message(all_idle),
            )
            logger.info(json.dumps({'notification': 'sns', 'topic': SNS_TOPIC_ARN}))
        except Exception:
            logger.error(json.dumps({'notification': 'sns', 'error': traceback.format_exc()}))

    return {
        'statusCode': 200,
        'body': json.dumps({'result': 'alert', 'dry_run': dry_run, 'idle_instances': all_idle}),
    }
