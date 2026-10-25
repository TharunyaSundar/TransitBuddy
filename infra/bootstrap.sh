#!/usr/bin/env bash
# One-time setup, run locally with admin AWS credentials: ./infra/bootstrap.sh
# Creates (idempotently) the S3 bucket for Terraform state and the IAM role GitHub Actions assumes via OIDC.
set -euo pipefail

REPO="${REPO:-TharunyaSundar/TransitBuddy}"
# GitHub now puts immutable ids in the OIDC subject: repo:<owner>@<owner_id>/<repo>@<repo_id>:...
# Allow both forms (still main branch of this repo only).
OWNER_ID="${OWNER_ID:-158185196}"
REPO_ID="${REPO_ID:-1432840244}"
SUB_NAME="repo:${REPO}:ref:refs/heads/main"
SUB_ID="repo:${REPO%%/*}@${OWNER_ID}/${REPO##*/}@${REPO_ID}:ref:refs/heads/main"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="transitbuddy-tfstate-${ACCOUNT_ID}"
ROLE="transitbuddy-github-deploy"
OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

echo "Account $ACCOUNT_ID, region $REGION, repo $REPO"

# --- state bucket
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  fi
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# --- GitHub OIDC provider (account-wide; reuse if it exists)
if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" >/dev/null 2>&1; then
  aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com >/dev/null
fi

# --- deploy role: only workflows on the main branch of this repo can assume it
TRUST=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Federated":"$OIDC_ARN"},
"Action":"sts:AssumeRoleWithWebIdentity",
"Condition":{"StringEquals":{"token.actions.githubusercontent.com:aud":"sts.amazonaws.com",
"token.actions.githubusercontent.com:sub":["${SUB_NAME}","${SUB_ID}"]}}}]}
JSON
)
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "$TRUST"
else
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" >/dev/null
fi

POLICY=$(cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":"ec2:*","Resource":"*"},
 {"Effect":"Allow","Action":["iam:CreateRole","iam:DeleteRole","iam:GetRole","iam:TagRole","iam:UntagRole",
  "iam:AttachRolePolicy","iam:DetachRolePolicy","iam:PutRolePolicy","iam:DeleteRolePolicy","iam:GetRolePolicy",
  "iam:ListRolePolicies","iam:ListAttachedRolePolicies","iam:ListInstanceProfilesForRole",
  "iam:CreateInstanceProfile","iam:DeleteInstanceProfile","iam:GetInstanceProfile","iam:TagInstanceProfile",
  "iam:UntagInstanceProfile","iam:AddRoleToInstanceProfile","iam:RemoveRoleFromInstanceProfile"],
  "Resource":["arn:aws:iam::${ACCOUNT_ID}:role/transitbuddy-*","arn:aws:iam::${ACCOUNT_ID}:instance-profile/transitbuddy-*"]},
 {"Effect":"Allow","Action":"iam:PassRole","Resource":"arn:aws:iam::${ACCOUNT_ID}:role/transitbuddy-*",
  "Condition":{"StringEquals":{"iam:PassedToService":"ec2.amazonaws.com"}}},
 {"Effect":"Allow","Action":["ssm:PutParameter","ssm:GetParameter","ssm:GetParameters","ssm:DeleteParameter",
  "ssm:AddTagsToResource","ssm:ListTagsForResource"],"Resource":"arn:aws:ssm:*:${ACCOUNT_ID}:parameter/transitbuddy/*"},
 {"Effect":"Allow","Action":"ssm:GetParameter","Resource":"arn:aws:ssm:*::parameter/aws/service/*"},
 {"Effect":"Allow","Action":"ssm:DescribeParameters","Resource":"*"},
 {"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::${BUCKET}"},
 {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::${BUCKET}/*"}
]}
JSON
)
aws iam put-role-policy --role-name "$ROLE" --policy-name deploy --policy-document "$POLICY"

cat <<EOT

Done. In GitHub (Settings > Secrets and variables > Actions) set:
  Secret   AWS_ROLE_ARN     = arn:aws:iam::${ACCOUNT_ID}:role/${ROLE}
  Variable TF_STATE_BUCKET  = ${BUCKET}
  Secrets  DISCORD_TOKEN, DISCORD_CLIENT_ID, DISCORD_GUILD_ID, MONGODB_URI, OLLAMA_API_KEY
EOT
