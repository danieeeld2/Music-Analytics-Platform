# Runbook: Connecting to RDS and applying the schema

Steps to connect to the RDS instance after `terraform apply`, and apply the database schema. Needed every time, since the instance is destroyed between sessions (on-demand deployment, see [ADR 0006](../adr/06-on-demand-deployment-no-24-7-uptime.md)).

## 1. Get the connection details from Terraform outputs

```bash
terraform output rds_endpoint
terraform output rds_secret_arn
```

## 2. Retrieve the auto-generated master password

```bash
aws secretsmanager get-secret-value \
  --secret-id '<rds_secret_arn>' \
  --region eu-west-1 \
  --query "SecretString" --output text
```

Returns `{"username":"...","password":"..."}`. Extract just the password value.

> **Note:** use single quotes around the secret ARN. It contains a literal `!` character, which bash interprets as history expansion inside double quotes, causing an `event not found` error.

> **Note:** the `--region` flag is required explicitly. Without it, `list-secrets`/`get-secret-value` may return empty/not-found results even though the secret exists, if your CLI's default region doesn't match.

## 3. Connect with psql

```bash
psql -h <rds_endpoint> -p 5432 -U <username> -d soundcloud_data_db
```

Enter the password when prompted. Avoid passing it directly in the command, since it contains shell-special characters (`!`, `(`, `*`, `[`, `~`).

## 4. Apply the schema

From within the `psql` session:

```sql
\i modules/rds/schema.sql
```

Or from bash directly:

```bash
psql -h <rds_endpoint> -p 5432 -U <username> -d soundcloud_data_db -f modules/rds/schema.sql
```

## 5. Verify

```sql
\dt
```

Should list `tracks`, `track_snapshots`, and `account_snapshots`.

---

Since the instance is destroyed after each session, this schema needs to be reapplied every time RDS is recreated. It isn't managed by Terraform itself (see [schema.sql](../../modules/rds/schema.sql)).
