# ADR 10: Open RDS ingress for Lambda instead of restricting by IP

**Status:** Accepted

## Context

ADR 03 restricted access to RDS using specific IP ranges, including my own IP and Grafana Cloud's IPs.

When I invoked the ingestion Lambda for the first time, it could not connect to RDS and eventually timed out. Lambda functions running outside a custom VPC do not have a fixed public IP, so the Security Group blocked the connection because only my own IP was allowed.

## Decision

Open the RDS ingress rule on port 5432 to `0.0.0.0/0` instead of restricting it by IP range.

The existing rule allowing my own IP is kept for local `psql` access, although it is now redundant because of the open rule.

## Alternatives

### Lambda inside the same VPC

One option was to put the Lambda inside the same VPC as RDS.

This could be done in a private subnet with a NAT Gateway. The NAT Gateway would be needed because the Lambda still needs internet access to call the SoundCloud API.

This was rejected because a NAT Gateway has a fixed monthly cost, which does not fit the zero-cost goal of the project described in ADR 03 and ADR 06.

Another option was to use a public subnet with an Elastic IP. This avoids the NAT Gateway cost, but adds more networking configuration such as route tables, an Internet Gateway and an Elastic IP.

This was also rejected because it adds complexity without providing a real security benefit for this use case.

## Consequences

### Positive

* No additional AWS cost.
* No new networking resources to manage.
* Lambda can connect to RDS without needing a fixed IP.

### Negative

RDS security now relies on database credentials instead of network-level IP restrictions. The credentials are managed through Secrets Manager.

This is a conscious trade-off for this portfolio project, which does not handle sensitive user data. It would not be an appropriate setup for a production environment handling real user data.
