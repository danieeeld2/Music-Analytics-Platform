# ADR 03: Use a public RDS endpoint instead of a private VPC

**Status: Accepted**

---

### Context

The data ingestion Lambda function needs to write to the RDS instance, while Grafana Cloud (an external SaaS) needs to read from it to generate the dashboard. A constraint of the project is to keep costs free or minimal.

### Decision

Use an RDS instance with a public endpoint, restricted by a Security Group to specific IP ranges (my IP + Grafana Cloud's published ranges).

### Alternatives

Using a private VPC with RDS in a private subnet is the correct or standard pattern for a real production environment; however, a Lambda function in a private subnet lacks default internet access. Consequently, a NAT Gateway is required, but its high cost makes it incompatible with the project.

### Consequences

#### Positive

Zero additional network cost, much simpler Terraform; no need to manage subnets, routing tables, or gateways, and allows Grafana Cloud to connect directly.

#### Negative

The RDS endpoint is technically reachable from the internet, with the Security Group serving as its only defensive layer.