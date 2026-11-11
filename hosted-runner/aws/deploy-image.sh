#!/usr/bin/env bash
# Build the runner image (linux/arm64, repo root as context) and push it to ECR.
# Usage: ./deploy-image.sh [tag]      (default tag: latest)
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
TAG="${1:-latest}"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker buildx build --platform linux/arm64 -f "$ROOT/hosted-runner/Dockerfile" \
  -t "${REGISTRY}/deepdoc-runner:${TAG}" --push "$ROOT"
echo "pushed ${REGISTRY}/deepdoc-runner:${TAG}"
