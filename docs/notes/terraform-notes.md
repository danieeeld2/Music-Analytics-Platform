# Terraform Notes - IAM, RDS & Bootstrap

> Personal notes on the Terraform work done for this project: what each block does, why it is written this way, and the problems I found along the way. Mostly for my own future reference. I am still learning Terraform, so I wrote down almost everything that was new or that tripped me up, even small things.

---

## 1. Overall structure

There are two separate Terraform configurations in this repo, each with its own state:

```
.
├── bootstrap/
│   └── main.tf      # S3 bucket + DynamoDB table, LOCAL state
└── main.tf           # IAM + RDS, REMOTE state (backend "s3")
```

Why two separate configurations? Terraform cannot use a backend before that backend exists. `bootstrap/` solves this by being applied once, manually, with local state. It creates the S3 bucket and DynamoDB table that the main configuration then uses as its remote backend.

---

## 2. Backend configuration

```hcl
backend "s3" {
  bucket         = "music-analytics-tfstate"
  key            = "music-analytics/terraform.tfstate"
  region         = "eu-west-1"
  dynamodb_table = "dynamo-table-music-analytics-tfstate"
}
```

`bucket` and `key` say where the `.tfstate` file itself lives in S3. `key` is like the "path" inside the bucket, useful if I ever reuse this same bucket for another project with a different key.

`dynamodb_table` is used for state locking. It stops two `apply` or `plan` operations from running at the same time and corrupting the state. It needs a table with a partition key literally named `LockID` (string type), Terraform expects that exact name.

Deprecation warning I keep seeing:
```
Warning: Deprecated Parameter
The parameter "dynamodb_table" is deprecated. Use parameter "use_lockfile" instead.
```
Since late 2024 Terraform supports native S3 locking through `use_lockfile = true`, which removes the need for a separate DynamoDB table entirely. I kept the classic DynamoDB pattern on purpose, because it is the pattern most people recognise when reviewing a repo, even if it is technically the one being phased out. Good to remember this exists in case I want to simplify it later.

Local vs remote state: I expected `terraform init` to ask whether to migrate the existing local state to the new S3 backend. It did not ask, because my previous `plan` and `validate` runs never reached a real `apply`, so there was no state to migrate. `init` just configured the new backend and that was it.

---

## 3. IAM

### Trust policy vs permission policy

This is the part that confused me the most at first, so writing it down properly.

`assume_role_policy` (inside `aws_iam_role`) is the trust policy. It answers "who is allowed to assume this role". For a Lambda execution role, the answer is the Lambda service itself:

```hcl
Principal = {
  Service = "lambda.amazonaws.com"
}
```

`aws_iam_role_policy` is the permission policy. It answers "once something has assumed this role, what is it actually allowed to do".

These are two different resources attached to the same role, and it is very easy to mix them up when writing from memory, which I did more than once.

### The Version field trap

```hcl
policy = jsonencode({
  Version = "2012-10-17"
  ...
})
```

I kept writing today's date here by mistake, like `"2026-09-01"`. This is wrong. `Version` here is not a date I choose, it is a fixed version string of the AWS policy language itself, and `"2012-10-17"` is basically the only value that should go here for a normal policy. Using anything else breaks the apply with a policy validation error. I made this mistake several times before it stuck.

### Least privilege

The Lambda permission policy only grants:

- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`. Baseline logging, every Lambda needs this or you get no logs at all if something fails.
- `ssm:GetParameter` and `ssm:PutParameter`, scoped to `arn:aws:ssm:*:*:parameter/music-analytics/*`, not `*`. Read for the current refresh_token, write because SoundCloud rotates it on every use (see ADR 07).
- `secretsmanager:GetSecretValue`, scoped to the exact ARN of the RDS master password secret, so the Lambda can read the DB credentials without me ever storing them in code or in a `.env` file inside Lambda.

---

## 4. RDS

### Why a subnet group is needed even for a "simple" public instance

Even without a custom VPC, RDS always requires an `aws_db_subnet_group` spanning at least 2 Availability Zones. This is a hard RDS requirement and has nothing to do with public or private access, which confused me since I was not planning to touch VPCs at all.

Solved without creating a VPC, by using data sources to query the account's already existing default VPC and its subnets:

```hcl
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
```

`data` blocks read existing infrastructure, they do not create anything new. `aws_subnets` (plural) returns a list through `.ids`. Using `.id` by mistake gives an "attribute not found" error, which I hit at least once.

### publicly_accessible, easy to silently get wrong

The default is `false`. Since ADR 03 says the endpoint should be public and restricted by the Security Group instead, this has to be set explicitly:

```hcl
publicly_accessible = true
```

If I forget this, Terraform does not throw any error. It just creates a non-public instance, and I would only notice later when I could not connect to it.

### manage_master_user_password, no password ever touches my code

```hcl
manage_master_user_password = true
```

AWS generates the master password on its own and stores it in Secrets Manager. I can get to it through:

```hcl
aws_db_instance.rds_db.master_user_secret[0].secret_arn
```

Note the `[0]`. This attribute is a list with one element, not a plain object, which is not obvious the first time you see it.

### Security Group, ingress vs egress, and the two rules I needed

Ingress (inbound) is who can reach RDS. Restricted to my own public IP (`/32` means exactly this IP, no range) per ADR 03.

Egress (outbound) is traffic leaving RDS. Security Groups block all outbound traffic by default unless you open it explicitly. I left this fully open (`0.0.0.0/0`, all ports), since the real protection here comes from the strict ingress rule, not from egress.

My own IP can change over time. If `psql` or the ingestion script suddenly cannot connect, the first thing to check is `curl -4 ifconfig.me`, before assuming something is broken in Terraform.

Grafana Cloud's IP is deliberately not hardcoded here. Their published ranges can change, so per ADR 08 I fetch them right before each demo session instead of keeping a permanent rule for them.

### engine_version, do not assume a version exists

First apply attempt failed with:
```
InvalidParameterCombination: Cannot find version 16.4 for postgres
```

I had picked `16.4` from memory or an older doc, and it was simply no longer offered by RDS. Lesson learned, always check what is currently available before hardcoding a version:

```bash
aws rds describe-db-engine-versions --engine postgres --region eu-west-1 \
  --query "DBEngineVersions[].EngineVersion" --output table
```

Ended up using `16.15`, the latest available in the 16.x line at the time.

### skip_final_snapshot, needed for a destroy and recreate workflow

Since this project follows an on-demand deploy strategy (spin up, demo, destroy, see ADR 06), I do not want AWS creating a final snapshot every time I tear the instance down. Without this, `terraform destroy` fails:

```
Error: final_snapshot_identifier is required when skip_final_snapshot is false
```

Fix:
```hcl
skip_final_snapshot = true
```

---

## 5. RDS Proxy, implemented, then removed

I originally added this mostly for portfolio value (see ADR 04). The real workload is one Lambda invocation per day, so it never really needed connection pooling.

`terraform apply` failed while creating it:
```
FreeTierRestrictionError: This feature isn't available with free plan accounts.
```

RDS Proxy is simply not available on the free or basic AWS account plan, something I only found out by trying to apply it for real, not while reading docs beforehand. I removed it completely (see ADR 09), the `aws_db_proxy`, `aws_db_proxy_default_target_group` and `aws_db_proxy_target` resources, plus the `rds_role` and `rds_policy` that only existed so the Proxy could reach Secrets Manager. The Lambda now reads the DB secret directly instead.

Lesson: `terraform plan` and `terraform validate` only check syntax and internal consistency. They do not catch account level restrictions like this one. Only a real apply against the real account shows this kind of problem.

---

## 6. Debugging tools that actually helped

`terraform validate` catches syntax errors, wrong argument names, and type mismatches, for example passing a single value where a list is expected. It never touches AWS at all.

`terraform plan` resolves the data sources and shows exactly what would be created, changed, or destroyed, without applying anything. This is what caught some of my wrong resource references early, like pointing to the wrong IAM role.

`terraform fmt -recursive` reformats everything to Terraform's standard 2 space style. I naturally write with 4 spaces, so I run this before every commit to keep the diff clean and to pass CI's `fmt -check`.

`aws sts get-caller-identity` confirms which IAM user or role is actually running Terraform right now. Useful when debugging permission errors, since it tells you exactly who is being denied what.

---

## 7. AWS CLI quirks found while testing the RDS connection by hand

Secret ARNs containing `!`, for example `rds!db-6cc4fd1e-...`, break inside double quoted bash strings. Bash reads `!` as history expansion and throws an `event not found` error. Fix is to use single quotes around the ARN instead.

`aws secretsmanager` commands need an explicit `--region`. Without it, `list-secrets` or `get-secret-value` can quietly return empty or not found results even though the secret exists, if the CLI's default region does not match.

Passwords generated by `manage_master_user_password` contain shell special characters like `!`, `(`, `*`, `[`, `~`. Never pass them directly on the command line, let `psql` prompt for the password interactively instead.

---

## 8. CI (GitHub Actions)

Added a `terraform-validate.yml` workflow, next to the existing one for the Python ingestion tests:

```yaml
- run: terraform fmt -check -recursive
- run: terraform init -backend=false
- run: terraform validate
```

The key detail is `-backend=false`. CI has no AWS credentials, and it does not need any just to validate the code. This flag tells `init` to download the providers without trying to reach the real S3 backend. There is no `terraform plan` in CI, since that would need real AWS credentials to inspect the current infrastructure. `validate` plus `fmt` is enough of a signal for this stage.

---

## 9. Tags

Added through `default_tags` inside the `provider "aws"` block, instead of repeating `tags = {...}` on every single resource:

```hcl
provider "aws" {
  region = "eu-west-1"

  default_tags {
    tags = {
      Project   = "music-analytics-platform"
      ManagedBy = "terraform"
      Component = "iam-rds" # or "bootstrap", depending on the file
    }
  }
}
```

This applies automatically to every resource that supports tags. Resources without a tags concept, like `aws_s3_bucket_public_access_block`, just ignore it, no error.

---

## 10. Things still pending

Add the Grafana Cloud ingress rule manually before each demo session (ADR 08), fetching the current IPs with:
```bash
curl -s https://allowlists.<region>.grafana.net/v1/grafana
```

Lambda plus EventBridge module, not written yet.

Modularize this single file configuration into `modules/iam/`, `modules/rds/`, `modules/lambda/`. Planned as a separate PR once the Lambda module also exists, instead of modularizing twice.
