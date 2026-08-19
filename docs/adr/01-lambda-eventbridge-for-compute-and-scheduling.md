# ADR 01: Use Lambda + EventBridge for compute and scheduling

**Status: Accepted**

---

### Context

The workflow consists of a lightweight data ingestion task (intended for personal use in this case) performed only once a day. I am looking for a minimum viable tool that allows me to accomplish this with minimal operational costs.

### Decision

Use an EventBridge trigger with a Scheduler Rule (`rate(1day)` or `cron()`), due to its simplicity and minimal cost.

### Alternatives

- **ECS**: Designed for containers that run continuously or on-demand with some degree of persistence (for example, an API that continuously processes messages from a queue). In my case, since the task involves only a single daily execution, using it would have meant over-provisioning the service.
- **Step Functions**: It is used to orchestrate multi-step workflows. In my case, since the workflow involves a single extraction function that doesn't trigger other functions based on its result, it didn't make sense either.

### Consequences

#### Positive

- Near 0 cost.
- Minimal infrastructure to define in Terraform.
- Simple deployment.

#### Negative

- 15-minute execution timeout ceiling (Not a real constraint today, but would become one if the ingestion logic grows significantly).