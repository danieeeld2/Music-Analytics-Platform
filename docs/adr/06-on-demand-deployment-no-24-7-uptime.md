# ADR 06: Deploy on-demand instead of running 24/7

**Status: Accepted**

---

### Context

The project is primarily for a portfolio; it is not a service that needs to be constantly available to third parties. The cost target is zero or near-zero.

### Decision

Deploy the stack on demand (using `terraform apply` to generate data and captures, and `terraform destroy` when it is no longer needed) instead of keeping it running permanently.

### Alternatives

Keeping it running 24/7 would offer the option of a live feed for viewing at any time, creating greater impact; but would entail ongoing costs.

### Consequences

#### Positive

Zero cost, aligned with the objective.

#### Negative

There is no live link to display; one is created on demand if requested, and screenshots demonstrating its operation are added to the README.