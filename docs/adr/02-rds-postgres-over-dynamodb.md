# ADR 02: RDS Postgres vs DynamoDB

**Status: Accepted**

---

### Context

I need to store daily snapshots of the metrics extracted from SoundCloud. Furthermore, I want the project to have some portfolio value, beyond simply solving the problem.

### Decision

Use RDS Postgres instead of DynamoDB.

### Alternatives

DynamoDB integrates natively with Lambda, as it requires no connection management or server provisioning. It was ruled out because (as I mentioned in the context) I want to add value to my portfolio; for that reason, I am more interested in using a relational database with SQL. Furthermore, this introduces a genuine connection management issue, which is the motivation behind one of the following ADRs (see [ADR 04](./04-rds-proxy-for-connection-pooling.md)).

### Consequences

#### Positive

A more expressive data model for analytics, with skills that are more transferable to Cloud/DevOps roles, where Postgres and MySQL remain the standard for many backends.

#### Negative

Higher potential cost than DynamoDB if left running continuously (mitigated by the [ADR 06](./06-on-demand-deployment-no-24-7-uptime.md) strategy); requires connection management via RDS Proxy (a deliberate choice for practice purposes); and necessitates defining the API response data schema upfront.