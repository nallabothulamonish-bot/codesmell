# M9 Architecture

## Components

- **Static-analysis core:** ingestion, Python AST parsing, metrics and rules.
- **Dataset/ML:** human-label workflow, project splits, nested tuning and LOGO.
- **Worker:** durable database queue, heartbeats, retries and cancellation.
- **Trusted inference:** verified model registry, predictions and XAI.
- **API:** FastAPI routes, role enforcement, project/job/results/report APIs.
- **Frontend:** React/TypeScript dashboard served by Nginx.
- **Persistence:** PostgreSQL/SQLite metadata and private file storage.
- **Gateway:** Caddy HTTPS in the production Compose topology.

## Data retained

The database stores metadata, metric vectors, findings, predictions,
explanations, recommendations, users, report metadata and audit events. It does
not store raw source text. Uploaded archives and generated artifacts live in
private persistent storage and source is expanded only into per-job sandboxes.

## Analysis flow

```text
Upload/repository -> Project row -> Queued job -> Worker claim
-> Hardened ingestion -> AST parse -> Metrics
-> Rule detection and/or trusted ML inference
-> Explanations/recommendations -> Persisted result
-> JSON/CSV/HTML/PDF report
```

## Trust boundaries

- Browser and uploaded projects are untrusted.
- API validates tokens and role permissions.
- Model registration is a trusted administrator action outside the public API.
- Worker never executes uploaded project code.
- Gateway terminates HTTPS and applies login rate limiting.
