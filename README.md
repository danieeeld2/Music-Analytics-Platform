# Music Analytics Platform

Turning my SoundCloud stats into an automated, self-hosted analytics dashboard.

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

As one of my hobbies is mixing electronic music, I upload my sets to SoundCloud but I have no visibility into how they perform over time. I usually ask myself how plays and engagement evolve or when might be the best time to release new tracks. This project solves that: An automated pipeline that fetches my SoundCloud stats daily, stores them and visualizes them on a dashboard.

Beyond the practical use, it's also a way of applying IaC and AWS serverless architecture to a real and self-motivated problem rather than tutorial exercises.

### Architecture

![Architecture diagram](./docs/images/architecture.png)

I use a Lambda function containing the bundled Python code responsible for data extraction. This function is triggered daily by EventBridge and stores the extracted data in a PostgreSQL RDS instance. A proxy is used for connection pooling, and the data is ultimately visualized on a Grafana dashboard.

These elements are created and maintained using Terraform; therefore, the `.tfstate` file must be stored remotely using S3 and DynamoDB for this purpose.

See [docs/adr/](./docs/adr/) for the reasoning behind each architecture decision.

### Tech Stack

- **Infrastructure**: Terraform, AWS (Lambda, EventBridge, RDS Postgres, RDS Proxy)
- **Data Ingestion**: Python (SoundCloud API)
- **Visualization**: Grafana Cloud
- **State Management**: S3 + DynamoDB

### Project Structure

```text
.
├── modules/
│   ├── lambda_src/       # Python ingestion pipeline (SoundCloud -> RDS)
│   │   ├── script.py
│   │   ├── get_initial_token.py
│   │   ├── test_script.py
│   │   └── requirements.txt
│   └── rds/
│       └── schema.sql    # Database schema (tracks, track_snapshots, account_snapshots)
├── docs/
│   ├── adr/              # Architecture decision records
│   └── images/
├── .github/workflows/    # CI: automated tests on every PR
└── README.md
```

*This tree reflects what exists today.*

### Setup / Deployment

### What this demonstrates

- OAuth2 authentication with a rotating, single-use refresh token (a non-trivial pattern requiring persistence across executions (see ADR 0007))
- API integration and data parsing with defensive handling of inconsistent fields (e.g. normalizing empty strings to `NULL`)
- Idempotent database writes (`ON CONFLICT DO NOTHING`) to safely support re-runs
- Automated testing (pytest) and CI (GitHub Actions) for the ingestion logic
- Documented architecture decisions and trade-offs (ADRs) throughout the project
- *(To come: Infrastructure as Code with Terraform, remote state management, event-driven serverless architecture)*

### Screenshots

### License

This project is licensed under the MIT License. See [LICENSE](./LICENSE) for details.
