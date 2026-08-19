# ADR 05: Use Grafana Cloud for dashboard visualization

**Status: Accepted**

---

### Context

A visualization layer is needed to clearly display the metrics stored in RDS, including screenshots suitable for a portfolio. Furthermore, one of the project's goals is to build a valuable portfolio for Cloud/DevOps and SRE roles, rather than for Front-End development.

### Decision

Use Grafana Cloud (free tier) as a visualization tool, connected to RDS Postgres as the data source.

### Alternatives

Creating a custom dashboard using a programming framework—though this would deviate from the project's objective, even if it would indeed allow for greater customization.

### Consequences

#### Positive

Aligned with the tools required in the target job market.

#### Negative

Dependency on a third-party service and opening the RDS Security Group to the external SaaS IP range.