#!/usr/bin/env bash
# Create the single-tenant LMS test stack in us-east-1 and print its URL.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
if [[ "$REGION" != "us-east-1" ]]; then
  echo "The Enigma account already uses us-east-1. Refusing to deploy elsewhere." >&2
  exit 1
fi
export AWS_DEFAULT_REGION="$REGION"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REPO="lms-test"
IMAGE="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:test"
DOCKER="${DOCKER:-docker}"

aws ecr describe-repositories --repository-names "$REPO" >/dev/null 2>&1 \
  || aws ecr create-repository \
       --repository-name "$REPO" \
       --image-scanning-configuration scanOnPush=true >/dev/null

aws ecr get-login-password \
  | "$DOCKER" login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

"$DOCKER" build -t "$IMAGE" "$ROOT"
"$DOCKER" push "$IMAGE"

aws cloudformation deploy \
  --stack-name lms-test \
  --template-file "$ROOT/deploy/aws/cloudformation.yml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides ImageUri="$IMAGE" \
  --no-fail-on-empty-changeset

aws cloudformation describe-stacks \
  --stack-name lms-test \
  --query "Stacks[0].Outputs" \
  --output table
