#!/usr/bin/env bash
# Remove the LMS test stack, its statement bucket, and the ECR repository.
set -euo pipefail

export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
STACK="lms-test"

BUCKET="$(aws cloudformation describe-stacks \
  --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" \
  --output text 2>/dev/null || true)"

if [[ -n "$BUCKET" && "$BUCKET" != "None" ]]; then
  aws s3 rm "s3://${BUCKET}" --recursive
fi

aws cloudformation delete-stack --stack-name "$STACK"
aws cloudformation wait stack-delete-complete --stack-name "$STACK"
aws ecr delete-repository --repository-name lms-test --force || true

echo "lms-test has been deleted."
