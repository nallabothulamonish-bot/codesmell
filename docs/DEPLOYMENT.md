# Production Deployment

## Topology

```text
Internet -> Caddy HTTPS -> Nginx React frontend -> FastAPI
                                              -> PostgreSQL
FastAPI/worker -> shared persistent analysis/report volume
```

Run migrations as a one-time deployment job before starting the API and worker.
Do not enable automatic migration in production.

## Required variables

```text
CODESMELL_DOMAIN
POSTGRES_PASSWORD
CODESMELL_JWT_SECRET
```

Initial bootstrap variables are optional when an administrator already exists:

```text
CODESMELL_ADMIN_EMAIL
CODESMELL_ADMIN_PASSWORD
CODESMELL_ADMIN_NAME
```

## Start

```bash
docker compose -f docker-compose.production.yml config
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml ps
docker compose -f docker-compose.production.yml logs -f migrate api worker gateway
```

## Health checks

```bash
curl -fsS https://$CODESMELL_DOMAIN/health/live
curl -fsS https://$CODESMELL_DOMAIN/health/ready
```

`live` verifies process availability. `ready` verifies database connectivity.

## Scaling

The database queue supports more than one worker. Start additional worker
replicas only after monitoring database contention and ensuring all replicas
mount the same persistent data volume.

```bash
docker compose -f docker-compose.production.yml up -d --scale worker=3
```

Do not scale the SQLite development configuration across processes.

## Backup

Back up both:

1. PostgreSQL, containing projects, jobs, metrics, findings, predictions,
   explanations, recommendations, users, reports and audit metadata.
2. `codesmell_data`, containing uploaded archives, trusted model artifacts and
   generated reports.

Test restoration regularly. A database backup without the data volume cannot
restore uploads/models/reports; a volume backup without the database cannot
reconstruct metadata and ownership.

## Upgrades

1. Back up database and data volume.
2. Build the new images.
3. Run the migration service.
4. Start API and workers.
5. Verify health endpoints and a test analysis.
6. Retain the previous image until verification succeeds.

## Logging and observability

Production logs are JSON. Collect logs from API, worker, database and gateway.
Use `X-Request-ID` to correlate HTTP activity with audit events. Monitor:

- queued/running/failed jobs
- stale-job recovery
- analysis latency
- upload and report volume
- authentication failures at the gateway
- database size and backup age
- worker CPU/memory
