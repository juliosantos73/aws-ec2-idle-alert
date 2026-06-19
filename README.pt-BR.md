# aws-ec2-idle-alert

🌐 [English](README.md) | [Português](README.pt-BR.md)

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-orange?logo=amazon-aws)

Uma função AWS Lambda que **detecta instâncias EC2 ociosas** consultando métricas de CPU no CloudWatch e envia alertas via SNS. Executa diariamente em todas as regiões via EventBridge.

---

## Como funciona

```
EventBridge (cron diário) ──► Lambda ──► describe_instances (running, todas as regiões)
                                     │       └── get_metric_statistics (CPUUtilization, últimas N horas)
                                     │               └── média CPU < CPU_THRESHOLD → ociosa
                                     │
                                     └── (se instâncias ociosas encontradas)
                                             └──► SNS Topic ──► E-mail
```

---

## Funcionalidades

- Verifica **todas as instâncias EC2 em execução em todas as regiões**
- **Threshold de CPU** e **janela de observação** (horas) configuráveis
- Inclui a tag `Name` da instância no alerta para fácil identificação
- Ignora instâncias sem dados no CloudWatch (ex: recém-iniciadas)
- Tratamento de erro por instância — uma falha não para a região
- Logs JSON estruturados — compatíveis com CloudWatch Insights
- Modo dry run — lista instâncias ociosas sem enviar notificações
- Retry adaptativo via botocore

---

## Pré-requisitos

- Uma conta AWS
- As instâncias EC2 devem ter o monitoramento padrão do CloudWatch ativo (5 minutos)
- Python 3.12+ (somente para desenvolvimento local)
- AWS CLI configurado (opcional)

> **Atenção:** Os dados de métricas do CloudWatch têm um atraso de até 5 minutos no monitoramento padrão. O Lambda consulta as últimas `IDLE_HOURS` horas de dados, portanto atividade muito recente pode não ser refletida.

---

## 1. Criar o tópico SNS

```bash
TOPIC_ARN=$(aws sns create-topic --name ec2-idle-alert --query TopicArn --output text)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint seu@email.com
echo "Topic ARN: $TOPIC_ARN"
```

---

## 2. Criar o IAM execution role

**Policy document** — salve como `ec2-idle-policy.json`:

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
      "Resource": "<arn-do-seu-topico-sns>"
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

## 3. Deploy da função Lambda

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

## 4. Configurar a regra do EventBridge

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

## Configuração

| Variável         | Padrão   | Descrição                                                       |
|------------------|----------|-----------------------------------------------------------------|
| `CPU_THRESHOLD`  | `5.0`    | Média de CPU (%) abaixo da qual a instância é considerada ociosa |
| `IDLE_HOURS`     | `24`     | Janela de observação em horas para a média de CPU               |
| `SNS_TOPIC_ARN`  | _(vazio)_| ARN do tópico SNS para notificações por e-mail                  |
| `DRY_RUN`        | `false`  | Defina como `true` para listar achados sem enviar notificações  |

---

## Testes

```bash
aws lambda invoke \
  --function-name ec2-idle-alert \
  --payload '{"dry_run":true}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json
```

---

## Exemplo de resposta

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

## Desenvolvimento local

```bash
pip install -r requirements-dev.txt
python -c "from lambda_function import lambda_handler; print(lambda_handler({'dry_run': True}, None))"
```

---

## Contribuindo

1. Faça um fork do repositório
2. Crie uma branch: `git checkout -b feature/sua-feature`
3. Faça commit, push e abra um Pull Request

---

## Licença

[MIT](LICENSE) — © Júlio César Santos
