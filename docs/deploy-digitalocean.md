# Deploying EdgeLedger to a DigitalOcean Droplet

EdgeLedger runs on one Droplet as the same Docker Compose stack used locally, plus Caddy for HTTPS. CircleCI builds and
tests every commit; on `main` it publishes the images to GitHub Container Registry (ghcr.io) and then deploys them to
the Droplet over SSH. Nothing is built on the server.

```
push to main -> CircleCI: tests, e2e, docker build + smoke test -> push images to ghcr.io -> ssh to Droplet -> pull + restart
```

## One-time setup

### 1. Create the Droplet

- In DigitalOcean: Create > Droplets. Image: Marketplace > **Docker on Ubuntu**. Size: at least **2 GB RAM**
  (Postgres, Redis, the API, the worker, nginx and Caddy together). Add your SSH key.
- Note the Droplet's public IP.

### 2. Point a domain at it

Add a DNS A record for the domain you want (for example `app.yourdomain.com`) pointing at the Droplet IP. If the domain
is managed in DigitalOcean: Networking > Domains. Caddy requests the HTTPS certificate on first start, so the record
must resolve before step 4 succeeds.

### 3. Prepare the server

```bash
ssh root@<droplet-ip>
mkdir -p /opt/edgeledger && cd /opt/edgeledger
# create .env from deploy/env.example in the repo:
cat > .env <<'ENV'
EL_DOMAIN=app.yourdomain.com
EL_SECRET_KEY=<output of: openssl rand -hex 32>
POSTGRES_PASSWORD=<output of: openssl rand -hex 24>
IMAGE_REPO=ghcr.io/utsav475908
IMAGE_TAG=latest
ENV
chmod 600 .env
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

Keep `POSTGRES_PASSWORD` unchanged after the first start: Postgres keeps the password the database was created with.

Make a deploy key for CircleCI and authorise it on the Droplet:

```bash
ssh-keygen -t ed25519 -N "" -C circleci-deploy -f ~/circleci_deploy
cat ~/circleci_deploy.pub >> ~/.ssh/authorized_keys
cat ~/circleci_deploy        # paste this private key into CircleCI (next step), then delete both files
```

Get the Droplet's host key so CircleCI can verify it is talking to your server. On your Mac:

```bash
ssh-keyscan -t ed25519 <droplet-ip>
```

Check the fingerprint matches what the Droplet itself reports (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on
the server, or the DigitalOcean console), then keep the `ssh-keyscan` output line for the next step.

### 4. Configure CircleCI

In the kumarzella project on circleci.com, Project Settings:

- **SSH Keys > Additional SSH Keys > Add SSH Key**: hostname = the Droplet IP, private key = the key above.
- **Environment Variables**:
  - `GHCR_USER` = `utsav475908`
  - `GHCR_TOKEN` = a GitHub personal access token (classic) with `write:packages` and `read:packages`
  - `GHCR_PULL_TOKEN` = a second token with only `read:packages` (recommended): the Droplet uses this one to pull,
    so it never sees a token that can publish. The login is not kept on the server after each deploy.
  - `DEPLOY_HOST` = the Droplet IP
  - `DEPLOY_KNOWN_HOSTS` = the `ssh-keyscan` line from step 3
  - `DEPLOY_USER` = `root` (optional; root is the default)

The next push to `main` (or Rerun workflow from the CircleCI UI) deploys. The app is then at `https://<EL_DOMAIN>`.

## Day to day

- Every push to `main` that passes the tests deploys automatically. Other branches run the tests only.
- Logs: `cd /opt/edgeledger && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api`
- Roll back to an earlier commit: `IMAGE_TAG=<older sha> ./deploy/remote-deploy.sh` on the server (each commit's images
  stay in ghcr.io), or re-run that commit's workflow in CircleCI.
- Demo data: `docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api python -m scripts.seed_demo`
- Backups: the database lives in the `edgeledger_pgdata` volume. Enable Droplet backups, or run
  `docker compose ... exec -T db pg_dump -U edgeledger edgeledger | gzip > backup.sql.gz` on a schedule.

## Notes

- Security: anyone who can push to `main` or re-run jobs in the CircleCI project can deploy, and a job re-run with SSH
  could read the deploy key. That is fine while you are the only member. If you add collaborators, move the deploy
  variables and key into a CircleCI context restricted to yourself, and use a non-root deploy user on the Droplet.

- Migrations run on every deploy (the `migrate` service) before the API starts.
- Uploads are stored in the `edgeledger_storage` volume on the Droplet.
- Market data is fetched from Dukascopy by the server, for each user's own trades. Get written permission from
  Dukascopy before offering the app commercially.
