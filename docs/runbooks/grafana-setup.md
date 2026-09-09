# Runbook: Connecting Grafana Cloud to RDS

Steps to reconnect the Grafana Cloud dashboard after RDS is recreated (on-demand deployment, see [ADR 0006](../adr/06-on-demand-deployment-no-24-7-uptime.md)). Needed every time, since the `grafanareader` user and the temporary Security Group rules do not persist across a `terraform destroy`.

## 1. Create the read-only database user

Run right after `init_db.sh`:

```bash
./init_grafana_user.sh
```

This creates (or recreates) the `grafanareader` Postgres user, with `SELECT` only on `tracks`, `track_snapshots`, and `account_snapshots`. See [ADR 0011](../adr/11-grafana-read-only-user.md) for why a dedicated user is used instead of the RDS master user.

The script prints the host, database name, username, and a freshly generated password. Keep this output, it's needed for step 3.

## 2. Allow Grafana Cloud's IPs through the Security Group

Grafana Cloud connects from a set of published IPs that can change over time (see [ADR 0008](../adr/08-grafana-network-access.md)). Fetch the current ones for the stack's region (`prod-eu-west-6`):

```bash
curl -s https://allowlists.prod-eu-west-6.grafana.net/v1/grafana
```

Update the `allow_grafana_1` / `allow_grafana_2` ingress rules in `main.tf` with the returned IPs if they changed, then:

```bash
terraform apply
```

## 3. Configure the data source in Grafana

In Grafana Cloud: **Connections > Add new connection > PostgreSQL > PostgreSQL data source**.

Fill in:

- **Host URL**: `<rds_endpoint>:5432` (from `terraform output rds_endpoint`)
- **Database name**: `soundcloud_data_db`
- **Username**: `grafanareader`
- **Password**: from step 1's script output
- **TLS/SSL Mode**: `require` (default, RDS requires at least this)

Click **Save & test**. Should confirm "Database Connection OK".

## 4. Verify the dashboard

Open the "Music Analytics Platform" dashboard. All 5 panels should show data:

- Snapshot (latest metrics per track, table)
- Plays per Tracks
- Likes per Tracks
- Repost per Tracks
- Followers

If a panel shows "Data outside time range" or plots `track_id` as if it were a value, double check the query's **Format** is set to **Time series**, not the default **Table**.

---

Query pattern used for each time-series panel:

```sql
SELECT
    snapshot_date AS time,
    playback_count,
    track_id::text AS track_id
FROM track_snapshots
ORDER BY snapshot_date
```

Swap `playback_count` for `favoritings_count` / `reposts_count` for the other per-track panels. The `track_id::text` cast makes Grafana treat it as a series label instead of a plottable value.
