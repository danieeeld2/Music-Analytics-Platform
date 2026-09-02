# Terraform Notes - IAM, RDS & Bootstrap

> Personal notes on the Terraform work done for this project: what each
> block does, why it is written this way, and the problems I found along
> the way. Mostly for my own future reference.

---

## 1. Overall structure

There are two separate Terraform configurations in this repo, each with its own state:

```
.
├── bootstrap/
│   └── main.tf      # S3 bucket + DynamoDB table - LOCAL state
└── main.tf           # IAM + RDS - REMOTE state (backend "s3")
```

**Why two separate configurations?** Terraform cannot use a backend before that backend exists. `bootstrap/` solves this by being applied once, manually, with local state. It creates the S3 bucket and DynamoDB table that the main configuration uses as its remote backend.

---

## 2. Backend configuration

```hcl backend "s3" {
  bucket         = "music-analytics-tfstate"
  key            = "music-analytics/terraform.tfstate"
  region         = "eu-west-1"
  dynamodb_table = "dynamo-table-music-analytics-tfstate"
}
```

- `bucket` / `key` - where the `.tfstate` file itself lives in S3. `key`
  is the "path" inside the bucket - useful if I ever reuse this same
  bucket for another project, with a different key.
- `dynamodb_table` - used for **state locking**: prevents two
  `apply`/`plan` operations from running at the same time and
  corrupting the state. Requires a table with a partition key literally
  named `LockID` (string type) - Terraform expects that exact name.

**Deprecation warning I keep seeing:**
```
Warning: Deprecated Parameter
The parameter "dynamodb_table" is deprecated. Use parameter "use_lockfile" instead.
```
Since late 2024, Terraform supports **native S3 locking** via
`use_lockfile = true`, removing the need for a separate DynamoDB table entirely. I kept the classic DynamoDB pattern on purpose - it's the more "recognizable" pattern for anyone reviewing the repo, even though it's technically the option being phased out. Worth remembering this exists in case I ever want to simplify it later.

**Local vs remote state:** I expected `terraform init` to ask whether to migrate the existing local state to the new S3 backend. It did not ask because my previous `plan`/`validate` runs never reached a real `apply`, so there was no state to migrate. `init` just configured the new backend.

---

## 3. IAM

### Trust policy vs permission policy

- **`assume_role_policy`** (inside `aws_iam_role`) - the *trust policy*.
  Answers: "who/what is allowed to assume this role?" For a Lambda
  execution role, the answer is the Lambda service itself:
  ```hcl
  Principal = {
    Service = "lambda.amazonaws.com"
  }
  ```
- **`aws_iam_role_policy`** - the *permission policy*. Answers: "once
  something has assumed this role, what is it allowed to do?"

These are two different resources attached to the same role. It is easy to mix them up when writing from memory.

### The `Version` field trap

```hcl policy = jsonencode({
  Version = "2012-10-17"
  ...
})
```

I kept writing today's date here (`"2026-09-01"`) by mistake. **This is wrong**. `Version` is not a date I choose. It is a fixed version string for the AWS policy language. `"2012-10-17"` is the value used here for a normal policy. Using another value causes a policy validation error.

### Least privilege

The Lambda permission policy only grants:
- `logs:CreateLogGroup/CreateLogStream/PutLogEvents` - baseline logging,
  every Lambda needs this.
- `ssm:GetParameter` + `ssm:PutParameter`, scoped to
  `arn:aws:ssm:*:*:parameter/music-analytics/*` - not `*`. Read for the
  current refresh_token, write because SoundCloud rotates it on every
  use (see ADR 07).
- `secretsmanager:GetSecretValue`, scoped to the exact ARN of the RDS
  master password secret - to read DB credentials without ever storing
  them in code or `.env` on Lambda.

---

## 4. RDS

### Why a subnet group is needed even for a "simple" public instance

Even without a custom VPC, RDS **always** requires an
`aws_db_subnet_group` spanning at least 2 Availability Zones. This is an
RDS requirement and is not related to public or private access.

Solved without creating a VPC, using data sources to query the account's already-existing default VPC and its subnets:

```hcl data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
```

`data` blocks **read** existing infrastructure. They do not create anything. `aws_subnets` (plural) returns a **list** through `.ids`. Using
`.id` by mistake gives an "attribute not found" error.

### `publicly_accessible` - easy to silently get wrong

The default is `false`. Since ADR 03 uses a public endpoint restricted by the Security Group, this must be set explicitly:

```hcl publicly_accessible = true
```

If this is missing, Terraform does not throw an error. It creates a non-public instance and you only notice when you cannot connect.

### `manage_master_user_password` - no password ever touches my code

```hcl manage_master_user_password = true
```

AWS generates the master password and stores it in **Secrets Manager**.
It can be accessed through:

```hcl aws_db_instance.rds_db.master_user_secret[0].secret_arn
```

Note the `[0]`. This attribute is a list with one element, not a plain object.

### Security Group - ingress vs egress, and the two rules I needed

- **Ingress** (inbound) - who can *reach* RDS. Restricted to my own
  public IP (`/32` = exactly this IP, no range) per ADR 03.
- **Egress** (outbound) - traffic *leaving* RDS. Security Groups block
  all outbound traffic by default unless opened explicitly - I left
  this fully open (`0.0.0.0/0`, all ports), since the actual protection
  comes from the restrictive ingress rule, not egress.

**My own IP can change**. If `psql` or the ingestion script suddenly cannot connect, check `curl -4 ifconfig.me` first before assuming there is a problem with Terraform.

**Grafana Cloud's IP** is deliberately *not* hardcoded here. Their published ranges can change, so according to ADR 08, I fetch them before each demo session instead of keeping a permanent rule.

### `engine_version` - don't assume a version exists

First `apply` attempt failed with:
```
InvalidParameterCombination: Cannot find version 16.4 for postgres
```

I had picked `16.4` from memory/older docs, but it was no longer offered by RDS. Always check which versions are currently available before hardcoding one:

```bash aws rds describe-db-engine-versions --engine postgres --region eu-west-1 \
  --query "DBEngineVersions[].EngineVersion" --output table
```

Ended up using `16.15` (latest available in the 16.x line at the time).

### `skip_final_snapshot` - needed for a destroy/recreate workflow

Since this project follows an on-demand deploy strategy (ADR 06, spin up, demo, destroy), I do not want AWS creating a final snapshot every time I destroy the instance. Without this, `terraform destroy` fails:

```
Error: final_snapshot_identifier is required when skip_final_snapshot is false
```

Fix:
```hcl skip_final_snapshot = true
```

---

## 5. RDS Proxy - implemented, then removed

Originally added for portfolio/demonstrative value (see ADR 04). The real workload is one Lambda invocation per day, so it does not need connection pooling.

`terraform apply` failed creating it:
```
FreeTierRestrictionError: This feature isn't available with free plan accounts.
```

RDS Proxy is not available on the free/basic AWS account plan. I only found this when applying the infrastructure for real. It was removed entirely (see ADR 09): the `aws_db_proxy`,
`aws_db_proxy_default_target_group` and `aws_db_proxy_target` resources, plus the `rds_role`/`rds_policy` that only existed for the Proxy to access Secrets Manager. The Lambda now reads the DB secret directly.

**Lesson**: `terraform plan` and `validate` check syntax and internal consistency, but they do not catch account-level restrictions like this.
A real `apply` against the account is needed to find this kind of issue.

---

## 6. Debugging tools that actually helped

- `terraform validate` - catches syntax errors, wrong argument names and
  type mismatches (for example, passing a single value where a list is
  expected). It does not connect to AWS.
- `terraform plan` - resolves data sources and shows what would be
  created, changed or destroyed without applying anything. It helped
  catch wrong resource references early, such as pointing to the wrong
  IAM role.
- `terraform fmt -recursive` - formats the files using Terraform's
  standard 2-space style. I normally write with 4 spaces, so I run this
  before every commit to keep the diff clean and pass CI's `fmt -check`.
- `aws sts get-caller-identity` - confirms which IAM user or role is
  running Terraform. Useful when debugging permission errors.

---

## 7. AWS CLI quirks encountered while testing the RDS connection manually

- **Secret ARNs containing `!`** (for example
  `rds!db-6cc4fd1e-...`) break inside **double-quoted** Bash strings.
  Bash interprets `!` as history expansion (`event not found`). Use
  single quotes around the ARN.
- **`aws secretsmanager` commands need an explicit `--region`**. Without
  it, `list-secrets` or `get-secret-value` can return empty/not-found even
  when the secret exists, if the CLI default region is different.
- Passwords generated by `manage_master_user_password` contain shell
  special characters (`!`, `(`, `*`, `[`, `~`) - never pass them
  directly on the command line; let `psql` prompt for them interactively
  instead.

---

## 8. CI (GitHub Actions)

Added a `terraform-validate.yml` workflow, alongside the existing workflow for the Python ingestion tests:

```yaml
- run: terraform fmt -check -recursive
- run: terraform init -backend=false
- run: terraform validate
```

**`-backend=false` is the key detail**. CI has no AWS credentials and does not need them just to validate the Terraform code. This flag tells
`init` to download the providers without connecting to the real S3 backend. There is no `terraform plan` in CI because that would require real AWS credentials. `validate` and `fmt` are enough for this check.

---

## 9. Tags

Added using `default_tags` in the `provider "aws"` block instead of repeating `tags = {...}` in every resource:

```hcl provider "aws" {
  region = "eu-west-1"

  default_tags {
    tags = {
      Project   = "music-analytics-platform"
      ManagedBy = "terraform"
      Component = "iam-rds"   # or "bootstrap", depending on the file
    }
  }
}
```

Applies automatically to every resource that supports tags. Resources without tags support, such as `aws_s3_bucket_public_access_block`, simply ignore it.

---

## 10. Things still pending

- Add the Grafana Cloud ingress rule manually before each demo session
  (ADR 08) - fetch current IPs with:
  ```bash
  curl -s https://allowlists.<region>.grafana.net/v1/grafana
  ```
- Lambda + EventBridge module (not written yet).
- Modularize this single-file configuration into `modules/iam/`,
  `modules/rds/`, `modules/lambda/` - planned as a separate PR once the
  Lambda module exists too, rather than modularizing twice.
