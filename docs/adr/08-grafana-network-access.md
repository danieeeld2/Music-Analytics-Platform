# ADR 08: Manage Grafana Cloud access to RDS

**Status: Accepted**

---

### Context

Grafana Cloud needs to connect to the RDS PostgreSQL instance to read the data and build the dashboards.

At first, the idea was to simply add Grafana Cloud's IP ranges to the RDS Security Group, in the same way as the personal IP was added in ADR 03. However, Grafana Cloud's official documentation explicitly states that these IP ranges can change and recommends getting them dynamically through its Allowlist API instead of hardcoding them.

It was also found that the "Grafana Assume Role" mechanism, using IAM `sts:AssumeRole`, is only available for the CloudWatch datasource. It cannot be used with the native PostgreSQL datasource used in this project.

Decision

Do not maintain a permanent Security Group rule for Grafana Cloud's IP ranges.

Since the project follows an on-demand deployment strategy (see ADR 06) and does not run 24/7, Grafana Cloud's IP ranges will be checked when needed for each demo or screenshot. They will then be added manually and temporarily to the RDS Security Group only during that session.

Before each demo/capture session, Grafana Cloud's current egress IPs are fetched using its Allowlist API:

```
curl -s https://allowlists.prod-eu-west-2.grafana.net/v1/grafana
```

The resulting CIDR ranges are added to the aws_vpc_security_group_ingress_rule for RDS. After applying the changes, the screenshots are taken and terraform destroy is run to remove the infrastructure.

### Alternatives

Automate the Allowlist API request using a Terraform `data source`, such as the `http` provider, and create the ingress rule dynamically on every `terraform apply`.

This was rejected for the current scope of the project because it adds unnecessary complexity and another external dependency that needs to be resolved during each plan/apply. This would be a better solution for a production system running 24/7, but it does not provide enough value for the current on-demand usage of this project.

### Consequences

#### Positive

Keeps the Terraform configuration simple, with no additional external dependencies.

It is also consistent with the project's low-cost and on-demand deployment strategy.

#### Negative

A manual step is required before each demo: check Grafana Cloud's Allowlist API and update the RDS Security Group.

If the project evolves into a real 24/7 system, this decision should be reviewed and the process should be automated.
