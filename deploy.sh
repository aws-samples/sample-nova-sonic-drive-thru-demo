#!/usr/bin/env bash
set -euo pipefail

# Deploy the Drive-Thru Voice Ordering system.
# Usage: ./deploy.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CDK_DIR="$SCRIPT_DIR/cdk"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

echo "=== Step 1: Build frontend ==="
cd "$FRONTEND_DIR"
npm ci
npm run build

echo ""
echo "=== Step 2: Deploy backend stack ==="
cd "$CDK_DIR"
# Activate the CDK venv so aws_cdk modules are available
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi
pip install -q -r requirements.txt
cdk deploy BackendStack --outputs-file "$CDK_DIR/backend-outputs.json" --require-approval never

echo ""
echo "=== Step 3: Generate runtime-config.json from backend outputs ==="
python3 "$SCRIPT_DIR/generate_config.py"
# Rebuild so dist/ carries the new config: the step 1 build (needed to synthesize the CDK app)
# copied the old public/runtime-config.json, which only matches when the backend IDs don't change.
cd "$FRONTEND_DIR"
npm run build

echo ""
echo "=== Step 4: Deploy frontend stack ==="
cd "$CDK_DIR"

# Read bucket name and distribution ID from backend outputs
BUCKET_NAME=$(python3 -c "import json; d=json.load(open('backend-outputs.json')); print(d['BackendStack']['HostingBucketName'])")
DIST_ID=$(python3 -c "import json; d=json.load(open('backend-outputs.json')); print(d['BackendStack']['DistributionId'])")

cdk deploy FrontendStack \
  --context hostingBucketName="$BUCKET_NAME" \
  --context distributionId="$DIST_ID" \
  --require-approval never

echo ""
echo "=== Step 5: Smoke test the live site ==="
# Checks what a browser hits (CSP, runtime config, images, agent endpoint). A healthy
# CloudFormation stack does not mean the site works, so a failure here fails the deploy.
python3 "$SCRIPT_DIR/smoke_test.py"

echo ""
echo "=== Done! ==="
DOMAIN=$(python3 -c "import json; d=json.load(open('backend-outputs.json')); print(d['BackendStack']['DistributionDomainName'])")
echo "App URL: https://$DOMAIN"
echo ""
echo "Create a Cognito user to sign in:"
USER_POOL_ID=$(python3 -c "import json; d=json.load(open('backend-outputs.json')); print(d['BackendStack']['UserPoolId'])")
echo "  aws cognito-idp admin-create-user --user-pool-id $USER_POOL_ID --username your@email.com --temporary-password TempPass123! --user-attributes Name=email,Value=your@email.com Name=email_verified,Value=true"
echo "  aws cognito-idp admin-set-user-password --user-pool-id $USER_POOL_ID --username your@email.com --password YourPassword123! --permanent"
