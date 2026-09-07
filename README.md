# Music Analytics Platform

Turning my SoundCloud stats into an automated analytics dashboard.

## Table of contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup / Deployment](#setup--deployment)
- [What this demonstrates](#what-this-demonstrates)
- [Screenshots](#screenshots)
- [License](#license)

---

### Overview

One of my hobbies is mixing electronic music, so I upload my sets to SoundCloud. However, I have no easy way to see how they perform over time. I usually ask myself how plays and engagement change or when might be the best time to release new tracks. This project solves that by fetching my SoundCloud stats daily, storing them and showing them on a dashboard.

It is also a way to apply IaC and AWS serverless architecture to a real problem that I chose myself, rather than a tutorial exercise.

### Architecture

![Architecture diagram](./docs/images/architecture.png)

A Lambda function runs the Python code that extracts the data, packaged with its dependencies as a Lambda Layer. It reads SoundCloud credentials from Parameter Store, reads the RDS master password from Secrets Manager, and writes the data directly to a PostgreSQL RDS instance. Right now the function is invoked manually for testing. It is meant to be triggered daily by EventBridge, which is still pending. The data is then visualized on a Grafana dashboard.

These resources are created and managed with Terraform. The remote state is stored in S3, with DynamoDB used for state locking.

An earlier version of this architecture included RDS Proxy for connection pooling ([old diagram](./docs/images/architecture-old.png)). It was removed after discovering that it is not available on free-tier AWS accounts. See [ADR 0009](./docs/adr/09-remove-rds-proxy.md) for the full reasoning.

Also worth noting: RDS ingress ended up open to all IPs on port 5432, not just my own, since Lambda does not have a fixed IP outside a custom VPC and a NAT Gateway would add real monthly cost. See [ADR 0010](./docs/adr/10-open-rds-ingress-for-lambda.md).

See [docs/adr/](./docs/adr/) for the reasoning behind the architecture decisions, and [docs/notes/](./docs/notes/) for more detailed notes on the Terraform implementation.

### Tech Stack

- **Infrastructure**: Terraform, AWS (Lambda, EventBridge, RDS Postgres)
- **Data Ingestion**: Python (SoundCloud API)
- **Visualization**: Grafana Cloud
- **State Management**: S3 + DynamoDB

### Project Structure

```text
.
├── bootstrap/             # S3 bucket + DynamoDB table for remote state (local state, applied once)
│   └── main.tf
├── modules/
│   ├── lambda_src/        # Python ingestion pipeline (SoundCloud -> RDS)
│   │   ├── script.py
│   │   ├── get_initial_token.py
│   │   ├── seed_parameter_store.py
│   │   ├── test_script.py
│   │   └── requirements.txt
│   └── rds/
│       └── schema.sql     # Database schema (tracks, track_snapshots, account_snapshots)
├── lambda_layer/          # Generated Lambda Layer (dependencies), not committed
├── main.tf                # IAM + RDS + Lambda infrastructure
├── build_layer.sh         # Rebuilds the Lambda Layer zip from requirements.txt
├── init_db.sh             # Applies schema.sql against RDS right after terraform apply
├── docs/
│   ├── adr/                # Architecture decision records
│   ├── notes/               # Technical study notes (Terraform, etc.)
│   ├── runbooks/             # Step-by-step operational guides
│   └── images/
├── .github/workflows/     # CI: automated tests + terraform validate on every PR
└── README.md
```

*This tree reflects the current project. It will grow with the EventBridge trigger and further modularization.*

### Setup / Deployment

After `terraform apply`, two manual steps are needed:

1. Apply the database schema, since a fresh RDS instance starts empty. Run `./init_db.sh`, or see [docs/runbooks/rds-setup.md](./docs/runbooks/rds-setup.md) for the manual step-by-step version.
2. Make sure SoundCloud credentials are in Parameter Store, with `modules/lambda_src/seed_parameter_store.py`.

Before applying the Lambda module, rebuild the Layer if dependencies changed: `./build_layer.sh`.

The CI workflow also rebuilds the Layer before running `terraform validate`, because the generated `lambda_layer/layer.zip` file is not committed to Git.

*(Full end-to-end deployment instructions will be added once the EventBridge trigger is in place.)*

### What this demonstrates

- OAuth2 authentication with a rotating, single-use refresh token, which needs to be stored between executions (see [ADR 0007](./docs/adr/07-refresh-token.md))
- API integration and data parsing, including handling inconsistent fields such as empty strings
- Idempotent database writes (`ON CONFLICT DO NOTHING`) to safely support re-runs
- Automated testing (pytest) and CI (GitHub Actions) for the ingestion code and Terraform configuration
- Infrastructure as Code with Terraform: remote state (S3 + DynamoDB), least-privilege IAM roles, a Lambda function with a dependencies Layer, and a public RDS endpoint
- Credential management split across Parameter Store (SoundCloud, free) and Secrets Manager (RDS, auto-generated), rather than defaulting to one service for everything
- Adapting architecture decisions after finding real deployment constraints (RDS Proxy unavailable on the free tier, Lambda's lack of a fixed IP forcing open RDS ingress), see [ADR 0009](./docs/adr/09-remove-rds-proxy.md) and [ADR 0010](./docs/adr/10-open-rds-ingress-for-lambda.md)
- Documented architecture decisions and trade-offs (ADRs) throughout the project
- *(To come: event-driven scheduling with EventBridge, once that trigger is in place)*

### Screenshots

### License

This project is licensed under the MIT License. See [LICENSE](./LICENSE) for details.
