#!/usr/bin/env bash
set -e

# Creates (or updates) the read-only "grafanareader" Postgres user used by
# the Grafana Cloud data source. Run this once, right after init_db.sh,
# every time RDS is recreated (on-demand deployment, see ADR 06).
#
# The grafanareader password is generated fresh on every run and printed
# at the end, since it needs to be pasted into the Grafana data source
# settings manually (see ADR 08 for why this isn't automated via
# Terraform/the Grafana provider yet).

RDS_ENDPOINT=$(terraform output -raw rds_endpoint)
RDS_SECRET_ARN=$(terraform output -raw rds_secret_arn)
DB_NAME="soundcloud_data_db"
REGION="eu-west-1"

echo "Fetching master user credentials from Secrets Manager..."
SECRET_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "$RDS_SECRET_ARN" \
  --region "$REGION" \
  --query "SecretString" --output text)

DB_USER=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['username'])")
DB_PASSWORD=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['password'])")

GRAFANA_PASSWORD=$(openssl rand -base64 24)

echo "Creating grafanareader user on $RDS_ENDPOINT..."
PGPASSWORD="$DB_PASSWORD" psql -h "$RDS_ENDPOINT" -p 5432 -U "$DB_USER" -d "$DB_NAME" <<SQL
DROP USER IF EXISTS grafanareader;
CREATE USER grafanareader WITH PASSWORD '$GRAFANA_PASSWORD';
GRANT USAGE ON SCHEMA public TO grafanareader;
GRANT SELECT ON tracks, track_snapshots, account_snapshots TO grafanareader;
SQL

echo ""
echo "grafanareader created successfully."
echo "Use these values in the Grafana PostgreSQL data source:"
echo "  Host:     $RDS_ENDPOINT:5432"
echo "  Database: $DB_NAME"
echo "  Username: grafanareader"
echo "  Password: $GRAFANA_PASSWORD"