# Terraform Notes - IAM, RDS, Lambda & Bootstrap

> Personal notes on the Terraform work done for this project: what each block does, why it is written this way, and the problems I found along the way. Mostly for my own future reference. I am still learning Terraform, so I wrote down almost everything that was new or that tripped me up, even small things.

---

## 1. Overall structure

There are two separate Terraform configurations in this repo, each with its own state:

```
.
├── bootstrap/
│   └── main.tf      # S3 bucket + DynamoDB table, LOCAL state
└── main.tf           # IAM + RDS + Lambda, REMOTE state (backend "s3")
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

### Security Group, ingress vs egress

Ingress (inbound) is who can reach RDS. Egress (outbound) is traffic leaving RDS. Security Groups block all outbound traffic by default unless you open it explicitly. I left egress fully open (`0.0.0.0/0`, all ports), since the real protection here comes from the ingress rules, not from egress.

My own IP can change over time. If `psql` or the ingestion script suddenly cannot connect, the first thing to check is `curl -4 ifconfig.me`, before assuming something is broken in Terraform.

Grafana Cloud's IP is deliberately not hardcoded here. Their published ranges can change, so per ADR 08 I fetch them right before each demo session instead of keeping a permanent rule for them.

I originally only allowed my own IP on ingress (ADR 03), but this had to change once Lambda entered the picture. See section 6 below.

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

## 6. Lambda function and Layer

### The Layer, what it actually is

A Layer is just a separate zip with dependencies, attached to the function, instead of bundling everything (code plus dependencies) into a single package. Lambda expects a very specific folder structure inside the zip: a top level folder literally called `python/`, with the installed packages inside it.

```bash
mkdir -p lambda_layer/python
pip install -r requirements.txt -t lambda_layer/python/
cd lambda_layer && zip -r layer.zip python && cd ..
```

Wrote this as `build_layer.sh` so I do not have to remember the exact commands every time dependencies change.

Note: this uses the full `requirements.txt`, which also has `boto3` and `pytest` in it. `boto3` is already preinstalled in the Lambda runtime and `pytest` is dev only, so the zip ends up a bit bigger than strictly needed. Kept it simple with one requirements file instead of maintaining a second one just for the layer.

### source_code_hash on the layer

```hcl
resource "aws_lambda_layer_version" "lambda_function_dependencies" {
  filename          = "./lambda_layer/layer.zip"
  layer_name        = "lambda_function_dependencies"
  source_code_hash  = filebase64sha256("./lambda_layer/layer.zip")
  compatible_runtimes = ["python3.10"]
}
```

`filebase64sha256()` reads the file and hashes its content. This is what lets Terraform notice that the zip changed even though its filename stayed the same, so it knows to publish a new Layer version on apply. Same idea I already knew from the Lambda function code hash below, just calculated manually here instead of coming from a data source.

### archive_file, so I do not zip the code by hand

```hcl
data "archive_file" "lambda_code" {
  type        = "zip"
  source_file = "./modules/lambda_src/script.py"
  output_path = "./modules/lambda_src/function.zip"
}
```

This is a `data` source from the `hashicorp/archive` provider (had to add it to `required_providers`). It zips `script.py` automatically on every `plan`/`apply`, so unlike the Layer, I never have to rebuild this one by hand when I edit the code. `output_base64sha256` on this data source gives me the hash directly, no need for `filebase64sha256()` here.

### The bug that cost me the most time here: missing `layers` argument

Wrote the whole `aws_lambda_function` block, `terraform plan` showed everything resolving fine, `apply` succeeded with no errors. First invoke:

```
{"errorMessage": "Unable to import module 'script': No module named 'requests'", "errorType": "Runtime.ImportModuleError"}
```

Checked the zip content with `unzip -l lambda_layer/layer.zip`, `requests` was there, correctly under `python/`. Checked the Layer version history in AWS, it existed too. The actual problem: I had simply never written the `layers = [...]` argument inside `aws_lambda_function` in the first place. Nothing was wrong with the Layer itself, the function just never referenced it. `terraform plan` does not warn you about a Lambda function with zero layers, since that is a perfectly valid (if useless, in this case) configuration.

```hcl
layers = [aws_lambda_layer_version.lambda_function_dependencies.arn]
```

Confirmed with:
```bash
aws lambda get-function-configuration --function-name ingestion_lambda_function --region eu-west-1 --query "Layers"
```
which returned `null` before the fix.

### handler format

```hcl
handler = "script.lambda_handler"
```

Format is `filename_without_extension.function_name`. My file is `script.py`, my entry point function is `lambda_handler`, so `script.lambda_handler`.

### timeout

Default Lambda timeout is only 3 seconds, way too short for an HTTP call plus DB inserts. Set `timeout = 300` (5 minutes), more than enough margin for this pipeline, which realistically takes a few seconds.

### Runtime version must match the Layer's build environment

`compatible_runtimes` on the Layer and `runtime` on the function both need to match the Python version I actually built the Layer with locally (`python3.10` in my case), or `psycopg2-binary`'s compiled binary parts might not work once deployed. Kept both pinned to `python3.10` to avoid this entirely.

---

## 7. Lambda has no fixed IP: had to reopen RDS ingress

First real invoke got past the import error, then failed again:

```
connection to server at "..." (52.209.242.80), port 5432 failed: Connection timed out
```

The Security Group only allowed my own IP (ADR 03). Lambda, running outside a custom VPC, does not have a fixed or predictable public IP, so it got blocked just like any other unknown IP would.

Considered putting the Lambda inside the same VPC as RDS, but that would mean either a NAT Gateway (real fixed monthly cost, exactly what ADR 03 was trying to avoid) or a public subnet with an Elastic IP (extra networking complexity for no real security gain here). Ended up just opening RDS ingress to `0.0.0.0/0` on port 5432 instead, see ADR 10 for the full writeup. Security now relies entirely on the Secrets Manager-generated password, not on network restriction. A conscious tradeoff for a project like this, not something I would do with real user data in production.

---

## 8. Debugging tools that actually helped

`terraform validate` catches syntax errors, wrong argument names, and type mismatches, for example passing a single value where a list is expected. It never touches AWS at all.

`terraform plan` resolves the data sources and shows exactly what would be created, changed, or destroyed, without applying anything. This is what caught some of my wrong resource references early, like pointing to the wrong IAM role. It did NOT catch the missing `layers` argument bug above though, since an empty layers list is valid Terraform, just not what I actually wanted.

`terraform fmt -recursive` reformats everything to Terraform's standard 2 space style. I naturally write with 4 spaces, so I run this before every commit to keep the diff clean and to pass CI's `fmt -check`.

`aws sts get-caller-identity` confirms which IAM user or role is actually running Terraform right now. Useful when debugging permission errors, since it tells you exactly who is being denied what.

`aws lambda get-function-configuration --query "Layers"` was the command that actually confirmed the Layer was not attached, when I was still assuming the problem was inside the zip itself.

---

## 9. AWS CLI quirks found while testing manually

Secret ARNs containing `!`, for example `rds!db-6cc4fd1e-...`, break inside double quoted bash strings. Bash reads `!` as history expansion and throws an `event not found` error. Fix is to use single quotes around the ARN instead.

`aws secretsmanager` commands need an explicit `--region`. Without it, `list-secrets` or `get-secret-value` can quietly return empty or not found results even though the secret exists, if the CLI's default region does not match.

Passwords generated by `manage_master_user_password` contain shell special characters like `!`, `(`, `*`, `[`, `~`. Never pass them directly on the command line, let `psql` prompt for the password interactively instead, or use `PGPASSWORD` as an environment variable inside a script (used this in `init_db.sh` to automate applying the schema after every apply).

---

## 10. CI (GitHub Actions)

Added a `terraform-validate.yml` workflow, next to the existing one for the Python ingestion tests. Key detail is `-backend=false` on `terraform init`, since CI has no AWS credentials and does not need any just to validate the code syntax.

Once the Lambda Layer entered the picture, `terraform validate` started failing in CI with:
```
Call to function "filebase64sha256" failed: open lambda_layer/layer.zip: no such file or directory
```
`lambda_layer/` is gitignored (it is a generated artifact, not source code), so it simply does not exist when CI checks out a fresh copy of the repo. Fixed by adding a step to the workflow that rebuilds the Layer zip in the runner before `validate` runs, same commands as `build_layer.sh`. `validate` only checks the Terraform is internally consistent, it does not care whether the zip's actual content makes sense, so building even a "throwaway" copy of it in CI is enough.

---

## 11. Tags

Added through `default_tags` inside the `provider "aws"` block, instead of repeating `tags = {...}` on every single resource. Applies automatically to every resource that supports tags. Resources without a tags concept, like `aws_s3_bucket_public_access_block`, just ignore it, no error.

---

## 12. EventBridge, daily trigger

Three resources needed, and it's easy to forget the third one:

`aws_cloudwatch_event_rule` — the schedule itself. Went with `schedule_expression = "rate(1 day)"` instead of a cron expression, since there's no need for a specific time of day. AWS cron syntax has 6 fields (not 5 like standard Linux cron), and needs a `?` in either the day-of-month or day-of-week field, can't have `*` in both at once. Didn't need to deal with that at all by using `rate()`.

`aws_cloudwatch_event_target` — connects the rule to the Lambda, just references both by name/ARN.

`aws_lambda_permission` — the one that's easy to skip. Without this, EventBridge has no actual permission to invoke the Lambda, even with the rule and target both configured correctly. `source_arn` scopes the permission to this specific rule only, not to any EventBridge rule in the account.

No real problems here, this part went smoothly once the Lambda itself was already working from the previous PR.

---

## 13. Grafana Cloud data source and dashboard

### PDC (Private Data Source Connect) doesn't apply here

Grafana Cloud can't reach databases on private IP ranges directly, you'd need PDC (a secure tunnel) for that. Since RDS here is public (ADR 03), none of this applies, the regular IP allowlist approach is enough.

### TLS/SSL Mode

RDS requires at least `require` mode. This is Grafana's default when adding a PostgreSQL data source, so no changes needed there. `verify-full` would need managing RDS's certificates, not worth it for this project.

### Dedicated read-only user instead of the RDS master user

Grafana's own docs are explicit about this: Grafana does not validate the safety of queries, so whoever has the credentials could run harmful SQL like `DROP TABLE`. Created a `grafanareader` user with only `SELECT` on the three tables, instead of pointing the data source at the master user. Automated with `init_grafana_user.sh`, generates a fresh password every run and prints it at the end. See ADR 11.

### Grafana Cloud's egress IPs, same problem as before

Same situation as the Lambda/RDS ingress issue really. Grafana Cloud connects from published IPs that can change, fetched from an allowlist API, same idea as ADR 08 describes:

```bash
curl -s https://allowlists.prod-eu-west-6.grafana.net/v1/grafana
```

Returns two IPs currently. Added as two separate `aws_vpc_security_group_ingress_rule` resources, since each one only takes a single `cidr_ipv4`, can't pass a list.

### Format: Table vs Format: Time series, the thing that confused me most here

First panel I built in Explore showed "Data outside time range" and a weird graph with `track_id` plotted as if it were a numeric value. The actual issue: the query editor defaults to **Format: Table**, and under that format Grafana doesn't know which column is meant to be time vs a value vs a label, it just shows whatever comes back.

Switching to **Format: Time series** fixed it immediately, once Grafana knows this is a time series query, it correctly uses the `time`-aliased column for the X axis and treats other numeric columns as values, string columns as series labels.

Two small things that helped:
- Aliasing the date column `AS time` explicitly, rather than relying on Grafana to guess from `snapshot_date`.
- Casting `track_id::text` so Grafana treats it as a label (one line per track) instead of trying to plot it as a number.

```sql
SELECT
    snapshot_date AS time,
    playback_count,
    track_id::text AS track_id
FROM track_snapshots
ORDER BY snapshot_date
```

### Only one data point so far

Since ingestion has only run a handful of times manually, each series shows isolated points rather than connected lines. This will fill in naturally once EventBridge has been running daily for a while.

---

## 14. Things still pending

Let this run for a few days with EventBridge actually triggering it, to get a dashboard with real connected lines instead of single points, for better screenshots.

Modularize the single `main.tf` into `modules/iam/`, `modules/rds/`, `modules/lambda/`, still planned as its own PR.
