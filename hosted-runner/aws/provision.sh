#!/usr/bin/env bash
# Idempotent AWS setup for the hosted generation runner (ECS Fargate, ARM64).
#
# Creates: ECR repo, CloudWatch log group, ECS cluster, the two task roles, the
# egress-only security group, the task definition, and a least-privilege IAM
# user that the Cloudflare Pages app uses to start/stop tasks.
#
# Usage:  AWS_REGION=us-east-1 ./provision.sh            # create/refresh everything
# The dispatch user's access key is NOT created here (see dispatch-key.sh) so it
# is never printed to a terminal.
#
# Secrets live in SSM Parameter Store (SecureString, free tier) under /deepdoc/.
# Set them with put-secret.sh; the task definition only references them by ARN.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
CLUSTER="deepdoc"
FAMILY="deepdoc-gen"
REPO="deepdoc-runner"
LOG_GROUP="/deepdoc/gen"
EXEC_ROLE="deepdoc-ecs-execution"
TASK_ROLE="deepdoc-gen-task"
DISPATCH_USER="deepdoc-dispatch"
SG_NAME="deepdoc-gen-egress"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:${IMAGE_TAG}"

# LLM defaults baked into the task definition (override per deploy).
# Default is gpt-oss-120b on Azure AI Foundry (Bedrock quotas were 0 on this
# account). The key is the SSM parameter /deepdoc/azure-api-key, injected below
# as AZURE_API_KEY. To use Bedrock again: DEEPDOC_LLM_MODEL=bedrock/converse/...
# DEEPDOC_LLM_PROVIDER=bedrock DEEPDOC_LLM_API_KEY_ENV= DEEPDOC_LLM_BASE_URL= ...
LLM_MODEL="${DEEPDOC_LLM_MODEL:-azure/gpt-oss-120b}"
LLM_PROVIDER="${DEEPDOC_LLM_PROVIDER-azure}"
LLM_KEY_ENV="${DEEPDOC_LLM_API_KEY_ENV-AZURE_API_KEY}"
LLM_BASE_URL="${DEEPDOC_LLM_BASE_URL-https://deepdoc-foundry-e2.services.ai.azure.com/}"
LLM_API_VERSION="${DEEPDOC_LLM_API_VERSION-2024-02-01}"
LLM_CONTEXT="${DEEPDOC_LLM_CONTEXT_TOKENS:-128000}"
LLM_RESERVE="${DEEPDOC_LLM_OUTPUT_RESERVE_TOKENS:-16000}"
# Per-generation hard cap (USD). Lower than the code default of 1.00 so a few
# runs cannot approach the account's $10 budget.
MAX_USD="${DEEPDOC_MAX_USD:-0.50}"

say() { printf '==> %s\n' "$*"; }

say "ECR repository"
aws ecr describe-repositories --region "$REGION" --repository-names "$REPO" >/dev/null 2>&1 \
  || aws ecr create-repository --region "$REGION" --repository-name "$REPO" \
       --image-scanning-configuration scanOnPush=true >/dev/null
aws ecr put-lifecycle-policy --region "$REGION" --repository-name "$REPO" --lifecycle-policy-text '{
  "rules":[{"rulePriority":1,"description":"keep last 5 images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":5},"action":{"type":"expire"}}]}' >/dev/null

say "CloudWatch log group"
aws logs create-log-group --region "$REGION" --log-group-name "$LOG_GROUP" 2>/dev/null || true
aws logs put-retention-policy --region "$REGION" --log-group-name "$LOG_GROUP" --retention-in-days 14

say "ECS cluster"
aws ecs describe-clusters --region "$REGION" --clusters "$CLUSTER" --query 'clusters[?status==`ACTIVE`].clusterName' --output text | grep -q "$CLUSTER" \
  || aws ecs create-cluster --region "$REGION" --cluster-name "$CLUSTER" >/dev/null

TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"'"$ACCOUNT_ID"'"}}}]}'

say "Execution role (pulls image, writes logs, reads /deepdoc/* secrets)"
aws iam get-role --role-name "$EXEC_ROLE" >/dev/null 2>&1 \
  || aws iam create-role --role-name "$EXEC_ROLE" --assume-role-policy-document "$TRUST" >/dev/null
aws iam attach-role-policy --role-name "$EXEC_ROLE" --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam put-role-policy --role-name "$EXEC_ROLE" --policy-name read-deepdoc-secrets --policy-document '{
  "Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ssm:GetParameters","ssm:GetParameter"],
  "Resource":"arn:aws:ssm:'"$REGION"':'"$ACCOUNT_ID"':parameter/deepdoc/*"}]}'

say "Task role (what the generation code itself may do: call Bedrock only)"
aws iam get-role --role-name "$TASK_ROLE" >/dev/null 2>&1 \
  || aws iam create-role --role-name "$TASK_ROLE" --assume-role-policy-document "$TRUST" >/dev/null
aws iam put-role-policy --role-name "$TASK_ROLE" --policy-name bedrock-invoke --policy-document '{
  "Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream","bedrock:Converse","bedrock:ConverseStream"],
  "Resource":["arn:aws:bedrock:*::foundation-model/*","arn:aws:bedrock:*:'"$ACCOUNT_ID"':inference-profile/*"]}]}'

say "Networking (default VPC, public IP, no inbound, no NAT cost)"
VPC_ID="$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
SG_ID="$(aws ec2 describe-security-groups --region "$REGION" --filters Name=group-name,Values="$SG_NAME" Name=vpc-id,Values="$VPC_ID" --query 'SecurityGroups[0].GroupId' --output text)"
if [ "$SG_ID" = "None" ]; then
  SG_ID="$(aws ec2 create-security-group --region "$REGION" --group-name "$SG_NAME" \
    --description "deepdoc generation tasks: egress only" --vpc-id "$VPC_ID" --query GroupId --output text)"
fi
SUBNETS="$(aws ec2 describe-subnets --region "$REGION" --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true --query 'Subnets[].SubnetId' --output text | tr '\t' ',')"

say "Task definition ${FAMILY} (4 vCPU / 8 GiB / ARM64, 40 GiB scratch)"
SSM="arn:aws:ssm:${REGION}:${ACCOUNT_ID}:parameter/deepdoc"
cat > /tmp/deepdoc-taskdef.json <<EOF
{
  "family": "${FAMILY}",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "4096",
  "memory": "8192",
  "runtimePlatform": {"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"},
  "ephemeralStorage": {"sizeInGiB": 40},
  "executionRoleArn": "arn:aws:iam::${ACCOUNT_ID}:role/${EXEC_ROLE}",
  "taskRoleArn": "arn:aws:iam::${ACCOUNT_ID}:role/${TASK_ROLE}",
  "containerDefinitions": [{
    "name": "runner",
    "image": "${IMAGE}",
    "essential": true,
    "command": ["python", "job.py"],
    "environment": [
      {"name": "AWS_REGION", "value": "${REGION}"},
      {"name": "AWS_REGION_NAME", "value": "${REGION}"},
      {"name": "DEEPDOC_LLM_MODEL", "value": "${LLM_MODEL}"},
      {"name": "DEEPDOC_LLM_PROVIDER", "value": "${LLM_PROVIDER}"},
      {"name": "DEEPDOC_LLM_API_KEY_ENV", "value": "${LLM_KEY_ENV}"},
      {"name": "DEEPDOC_LLM_BASE_URL", "value": "${LLM_BASE_URL}"},
      {"name": "DEEPDOC_LLM_API_VERSION", "value": "${LLM_API_VERSION}"},
      {"name": "DEEPDOC_LLM_CONTEXT_TOKENS", "value": "${LLM_CONTEXT}"},
      {"name": "DEEPDOC_LLM_OUTPUT_RESERVE_TOKENS", "value": "${LLM_RESERVE}"},
      {"name": "DEEPDOC_MAX_USD", "value": "${MAX_USD}"}
    ],
    "secrets": [
      {"name": "AZURE_API_KEY", "valueFrom": "${SSM}/azure-api-key"},
      {"name": "R2_ACCESS_KEY_ID", "valueFrom": "${SSM}/r2-access-key-id"},
      {"name": "R2_SECRET_ACCESS_KEY", "valueFrom": "${SSM}/r2-secret-access-key"},
      {"name": "RECONCILE_SECRET", "valueFrom": "${SSM}/reconcile-secret"}
    ],
    "logConfiguration": {"logDriver": "awslogs", "options": {
      "awslogs-group": "${LOG_GROUP}", "awslogs-region": "${REGION}", "awslogs-stream-prefix": "gen"}}
  }]
}
EOF
aws ecs register-task-definition --region "$REGION" --cli-input-json file:///tmp/deepdoc-taskdef.json \
  --query 'taskDefinition.taskDefinitionArn' --output text

say "Dispatch user (used only by the Cloudflare Pages app: RunTask/StopTask on this cluster)"
aws iam get-user --user-name "$DISPATCH_USER" >/dev/null 2>&1 || aws iam create-user --user-name "$DISPATCH_USER" >/dev/null
aws iam put-user-policy --user-name "$DISPATCH_USER" --policy-name dispatch-only --policy-document '{
  "Version":"2012-10-17","Statement":[
   {"Effect":"Allow","Action":"ecs:RunTask","Resource":"arn:aws:ecs:'"$REGION"':'"$ACCOUNT_ID"':task-definition/'"$FAMILY"':*",
    "Condition":{"ArnEquals":{"ecs:cluster":"arn:aws:ecs:'"$REGION"':'"$ACCOUNT_ID"':cluster/'"$CLUSTER"'"}}},
   {"Effect":"Allow","Action":["ecs:StopTask","ecs:DescribeTasks"],"Resource":"arn:aws:ecs:'"$REGION"':'"$ACCOUNT_ID"':task/'"$CLUSTER"'/*"},
   {"Effect":"Allow","Action":"iam:PassRole",
    "Resource":["arn:aws:iam::'"$ACCOUNT_ID"':role/'"$EXEC_ROLE"'","arn:aws:iam::'"$ACCOUNT_ID"':role/'"$TASK_ROLE"'"],
    "Condition":{"StringEquals":{"iam:PassedToService":"ecs-tasks.amazonaws.com"}}}]}'

cat <<EOF

Done. Values the Cloudflare Pages app needs (plain vars, not secrets):
  AWS_REGION=${REGION}
  ECS_CLUSTER=${CLUSTER}
  ECS_TASK_DEFINITION=${FAMILY}
  ECS_SUBNETS=${SUBNETS}
  ECS_SECURITY_GROUP=${SG_ID}
EOF
