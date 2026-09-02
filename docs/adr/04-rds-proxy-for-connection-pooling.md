# ADR 04: Use RDS Proxy for connection pooling

**Status: Superseded by [ADR 09](./09-remove-rds-proxy.md)**

---

### Context

Each concurrent invocation of a Lambda function opens its own connection to Postgres (connections are not shared across different function instances, unless a "warm start" occurs). RDS Postgres has a limit on simultaneous connections that depends on the instance size. Since the project aims to minimize costs, the instance size will be minimal, and consequently, so will the number of connections it can handle.

**Note**: In reality, there will only be one login per day (since there is only one user: myself), but because using the project as a portfolio piece is one of the project's objectives, I decided to include this feature.

### Decision

Use RDS Proxy as an intermediate pooling layer between Lambda and RDS.

### Alternatives

Do not use a proxy; instead, connect the Lambda directly to RDS, as the load is minimal (as mentioned in the context). However, this approach is included, as explained in the Note above, to add value to the project.

### Consequences

#### Positive

Protects against connection exhaustion if the ingestion frequency increases in the future.

#### Negative

A small additional cost, not covered by the free tier, and an extra component that needs to be maintained within the architecture.