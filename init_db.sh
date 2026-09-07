#!/usr/bin/env bash
set -e

# Applies modules/rds/schema.sql against the RDS instance just created by
# Terraform. Run this once, right after `terraform apply`, since a fresh
# RDS instance starts empty (the schema isn't managed by Terraform itself).
#
# See docs/runbooks/rds-setup.md for the manual step-by-step version of
# what this script automates.

RDS_ENDPOINT=$(terraform output -raw rds_endpoint)
RDS_SECRET_ARN=$(terraform output -raw rds_secret_arn)
DB_NAME="soundcloud_data_db"
REGION="eu-west-1"

echo "Fetching DB credentials from Secrets Manager..."
SECRET_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "$RDS_SECRET_ARN" \
  --region "$REGION" \
  --query "SecretString" --output text)

DB_USER=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['username'])")
DB_PASSWORD=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['password'])")

echo "Applying schema to $RDS_ENDPOINT..."
PGPASSWORD="$DB_PASSWORD" psql -h "$RDS_ENDPOINT" -p 5432 -U "$DB_USER" -d "$DB_NAME" -f modules/rds/schema.sql

echo "Schema applied successfully."
