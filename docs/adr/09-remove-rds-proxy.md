# ADR 09: Remove RDS Proxy due to AWS account restrictions

**Status: Accepted**

---

### Context

RDS Proxy was implemented following the decision made in ADR 04. The main reason was to demonstrate knowledge of RDS Proxy in the portfolio, rather than a real need for connection pooling, since the Lambda only runs once per day.

The Terraform configuration initially included:

```hcl
resource "aws_db_proxy" "rds_proxy" {
    name = "rds-proxy"
    engine_family = "POSTGRESQL"
    vpc_security_group_ids = [ aws_security_group.rds_security_group.id ]
    vpc_subnet_ids = data.aws_subnets.default.ids
    role_arn = aws_iam_role.rds_role.arn

    auth {
        auth_scheme = "SECRETS"
        iam_auth = "DISABLED"
        description = "Auth against RDS using the auto-generated master password secret"
        secret_arn = aws_db_instance.rds_db.master_user_secret[0].secret_arn
    }
}

resource "aws_db_proxy_default_target_group" "default_rds_proxy_target" {
    db_proxy_name = aws_db_proxy.rds_proxy.name

    connection_pool_config {
        connection_borrow_timeout = 120
        init_query = "SET x=1, y=2"
        max_connections_percent = 100
        max_idle_connections_percent = 50
        session_pinning_filters = ["EXCLUDE_VARIABLE_SETS"]
    }

    lifecycle {
        replace_triggered_by = [ aws_db_proxy.rds_proxy.id ]
    }
}

resource "aws_db_proxy_target" "rds_proxy_target" {
    db_instance_identifier = aws_db_instance.rds_db.id
    db_proxy_name = aws_db_proxy.rds_proxy.name
    target_group_name = aws_db_proxy_default_target_group.default_rds_proxy_target.name

    lifecycle {
        replace_triggered_by = [ aws_db_proxy.rds_proxy.id ]
    }
}
```

When running `terraform apply` against the real AWS account, the creation of the proxy failed with the following error:

```text
Error: creating RDS DB Proxy (rds-proxy): operation error RDS: CreateDBProxy, https response error StatusCode: 400, RequestID: 45c97019-6fcb-48bb-9072-fc027367c218, api error FreeTierRestrictionError: This feature isn’t available with free plan accounts. To remove all limitations, upgrade your account plan.

with aws_db_proxy.rds_proxy,
on main.tf line 174, in resource "aws_db_proxy" "rds_proxy":
174: resource "aws_db_proxy" "rds_proxy" {
```

This restriction was not identified during the design phase and was only discovered when applying the infrastructure to the real AWS account.

### Decision

Remove RDS Proxy from the architecture.

The Lambda will connect directly to the RDS PostgreSQL instance. The database credentials are automatically stored in Secrets Manager using `manage_master_user_password`, and the Lambda accesses the secret through the `secretsmanager:GetSecretValue` permission in its execution role.

This avoids upgrading the AWS account or paying additional costs for a feature that is not needed for the current workload.

### Alternatives

Upgrade the AWS account plan to use RDS Proxy.

This was rejected because it would add an extra cost that is not justified for a portfolio project with only one Lambda invocation per day. ADR 04 already identified that RDS Proxy was not strictly necessary for this workload and was mainly included for its demonstrative value.

### Consequences

#### Positive

Removes a component and a cost that are not covered by the free plan.

Simplifies the architecture, with fewer IAM and networking resources to maintain.

The Lambda no longer needs the additional `rds_role` and only uses its own execution role.

#### Negative

The project no longer demonstrates the use of RDS Proxy.

If the ingestion frequency increases significantly in the future, for example from once per day to once per minute, this decision should be reviewed. Without connection pooling, connection management could become more important. For the current workload, however, the risk of running out of database connections is practically zero, as already discussed in ADR 04.

### Note

This ADR documents a real infrastructure restriction discovered during implementation rather than during the design phase. The original architecture decision had to be changed after testing it against the real AWS account.

This is also a useful example of how architecture decisions can change when they meet the actual limitations and costs of the target environment.
