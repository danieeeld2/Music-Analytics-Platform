# ADR 07: Use Authorization Code flow with refresh token persistence instead of Client Credentials

**Status: Accepted**

---

### Context

The data needed by the project (own tracks, plays, likes, reposts) is available through the `/me/*` endpoints of the SoundCloud API. According to the official API specification, these endpoints explicitly require an access token obtained through the **Authorization Code** flow. The **Client Credentials** flow is simpler and is intended to authenticate the application itself (without a user), but it is only supported for public data endpoints (for example, `search`).

This was discovered after reviewing the complete OpenAPI specification of the API, since the authentication flow was initially designed assuming Client Credentials.

### Decision

Use the Authorization Code flow to obtain the initial `access_token` and `refresh_token` through a manual user login (myself), performed only once outside the automated infrastructure.

The resulting `refresh_token` is stored in Parameter Store, and the Lambda function uses it on each daily execution to obtain a new `access_token` (which has a short lifetime of around 1 hour) using the `refresh_token` flow.

Since SoundCloud provides a new single-use `refresh_token` after each refresh, the Lambda function also writes the new `refresh_token` back to Parameter Store on each execution, replacing the previous one.

### Alternatives

Keeping Client Credentials was not a viable option. It is not an alternative discarded by preference, but one that the API does not allow for the required use case (access to the user's own data). Therefore, it is discarded due to a technical incompatibility rather than a design choice.

### Consequences

#### Positive

Full access to the user's own endpoints (`/me/tracks`, `/me/likes/tracks`, `/me/reposts/tracks`, etc.), which are the ones that actually provide value to the project.

The refresh process is fully automated after the initial login, so the Lambda function does not require human intervention for daily operation.

It also documents a real and non-trivial authentication pattern (OAuth2 with a single-use rotating refresh token), which provides demonstrable value in an interview.

#### Negative

It requires a single manual and non-reproducible step before the first deployment, which partially breaks the "everything reproducible as code" approach used in the rest of the project. The initial token cannot be generated automatically because this is inherent to how OAuth works with user approval, rather than an avoidable limitation.

The Lambda execution IAM role also needs additional write permissions for Parameter Store (`ssm:PutParameter`), not only read permissions, slightly increasing its permission scope compared to the original design.

The SSM parameter storing the token must be managed outside Terraform (created manually, rather than as an `aws_ssm_parameter` resource), to prevent a `terraform destroy` of the stack from deleting the token together with the rest of the infrastructure.