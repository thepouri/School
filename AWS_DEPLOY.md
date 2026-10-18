# Skool Explorer — AWS Production Deployment Playbook

This guide provides end-to-end instructions for deploying the **Skool Explorer** stack (React 19 Frontend + FastAPI Backend + PostgreSQL 16 + Harvester Scheduler) on Amazon Web Services (AWS EC2 or AWS Lightsail).

---

## 1. Architecture & Stack Overview

The stack is containerized and orchestrated via Docker Compose into four interconnected services:

```
                          Internet (HTTP:80 / HTTPS:443)
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │            web (Nginx)            │
                     │  - React 19 SPA (Static Assets)   │
                     │  - Gzip & 1-Year Asset Caching    │
                     │  - SPA Routing Fallback           │
                     │  - Reverse Proxy for /api/*       │
                     └─────────────────┬─────────────────┘
                                       │
                         Internal Network (skool-net)
                                       │
                ┌──────────────────────┴──────────────────────┐
                ▼                                             ▼
     ┌─────────────────────┐                       ┌─────────────────────┐
     │     api (FastAPI)   │                       │      scheduler      │
     │  - Hexagonal API    │                       │  - 3-Day Refresh    │
     │  - Non-root user    │                       │  - Weekly Discovery │
     │  - Port 3001        │                       │  - Time-series Data │
     └──────────┬──────────┘                       └──────────┬──────────┘
                │                                             │
                └──────────────────────┬──────────────────────┘
                                       ▼
                     ┌───────────────────────────────────┐
                     │         db (PostgreSQL 16)        │
                     │  - Persistent Volume              │
                     │  - Port 5432 (Localhost only)     │
                     │  - Healthcheck: pg_isready        │
                     └───────────────────────────────────┘
```

---

## 2. Recommended AWS Infrastructure

### 2.1 Compute Options

| Cloud Provider Option | Instance Type / Plan | Specs | Estimated Cost | Notes |
|---|---|---|---|---|
| **AWS EC2 (Recommended)** | `t3.medium` | 2 vCPU, 4 GiB RAM, 30 GB gp3 SSD | ~$30 / month | Burstable CPU, supports AWS ALB & ACM SSL |
| **AWS Lightsail (Budget)** | 4 GB Plan | 2 vCPU, 4 GiB RAM, 80 GB SSD, 3 TB transfer | $20 / month | Fixed monthly pricing, simple snapshotting |

> **RAM Sizing Justification**:
> - PostgreSQL 16: ~512 MB – 1 GB shared buffers & work memory
> - FastAPI backend (2 workers): ~300 MB RAM
> - Nginx web server: ~50 MB RAM
> - Scraper & Scheduler daemon: ~400 MB – 800 MB during batch crawling passes
> - Docker build overhead: ~1.2 GB peak RAM during `npm run build`
> Total operational RAM requirement is ~2.5–3.5 GB. A 4 GB RAM instance provides stable headroom.

### 2.2 Swap Memory Configuration (Mandatory)

Even on 4 GB instances, configure 2 GB of swap memory to safeguard against out-of-memory (OOM) process kills during parallel container image builds or heavy scraper runs:

```bash
# Allocate 2GB swap file
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make swap permanent across reboots
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Verify swap activation
free -h
```

---

## 3. Server Provisioning & OS Setup

### 3.1 Supported Operating System
- **Ubuntu 24.04 LTS** (Noble Numbat) or **Ubuntu 22.04 LTS** (Jammy Jellyfish).

### 3.2 System Update & Docker Installation

Run the following commands on your EC2 / Lightsail instance:

```bash
# Update package repositories
sudo apt-get update && sudo apt-get upgrade -y

# Install prerequisite utilities
sudo apt-get install -y curl wget git ufw htop ca-certificates gnupg

# Install Docker Engine & Docker Compose via official Docker script
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add current user to docker group (avoids needing sudo for docker commands)
sudo usermod -aG docker $USER

# Apply group changes immediately (or log out and back in)
newgrp docker

# Verify installation
docker --version
docker compose version
```

---

## 4. Security Group & Firewall Configuration

### 4.1 AWS Security Group Rules (EC2 Console / Lightsail Networking)

Configure your AWS Security Group with the following inbound rules:

| Type | Protocol | Port Range | Source | Purpose |
|---|---|---|---|---|
| **SSH** | TCP | `22` | `YOUR_IP/32` (or your company CIDR) | Secure shell access (DO NOT leave open to 0.0.0.0/0) |
| **HTTP** | TCP | `80` | `0.0.0.0/0` | Web traffic and Let's Encrypt validation |
| **HTTPS** | TCP | `443` | `0.0.0.0/0` | Secure SSL/TLS web traffic |
| **PostgreSQL** | TCP | `5432` | **DENY / BLOCKED** | Never expose database ports to the public internet |

### 4.2 Host-level Firewall (UFW)

Enable the local Linux firewall on the server:

```bash
# Default policies: deny inbound, allow outbound
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow SSH, HTTP, and HTTPS
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw --force enable

# Verify status
sudo ufw status verbose
```

---

## 5. Deploying the Application Stack

### 5.1 Clone or Copy Repository

Clone the project to `/opt/skool` (standard server deployment path):

```bash
sudo mkdir -p /opt/skool
sudo chown -R $USER:$USER /opt/skool

# Clone repository
git clone <YOUR_GIT_REPOSITORY_URL> /opt/skool
cd /opt/skool
```

### 5.2 Configure Production Environment Variables

Copy the production template `.env.production` to `.env`:

```bash
cp .env.production .env
```

Generate a cryptographically secure JWT secret and database password:

```bash
# Generate 48-byte secure URL-safe secret
python3 -c "import secrets; print('AUTH_JWT_SECRET=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))"
```

Edit `/opt/skool/.env` and update:
- `POSTGRES_PASSWORD`: Use the generated database password.
- `AUTH_JWT_SECRET` and `JWT_SECRET`: Use the generated JWT secret.
- `DATABASE_URL`: Ensure the password matches `POSTGRES_PASSWORD`.
- `ADMIN_EMAIL` and `ADMIN_PASSWORD`: Set your initial administrator credentials.

```bash
nano .env
```

### 5.3 Build and Launch Stack

Launch the entire stack with a single command:

```bash
docker compose up -d --build
```

Docker Compose will:
1. Build the multi-stage React 19 frontend container and pack static assets into Nginx.
2. Build the lean Python 3.11 backend container with non-root security.
3. Build the scraper scheduler container.
4. Pull and run PostgreSQL 16 with a persistent Docker volume (`skool_postgres_data`).
5. Wire up the internal network and start services in dependency order (`db` -> `api` & `scheduler` -> `web`).

---

## 6. Database Initialization & Admin Setup

### 6.1 Database Schema Verification

On first startup, the FastAPI backend automatically initializes the `app` schema (`app.accounts` and `app.usage_log`).

Check the database health probe:
```bash
docker compose exec db pg_isready -U skool -d skool
```

### 6.2 Restoring Existing Skool Data (Optional)

If migrating from an existing dump file (`skool.dump`):

```bash
# Copy dump file into container and restore
docker compose exec -T db pg_restore -U skool -d skool --no-owner --clean < skool.dump
```

If initializing tables from Python models:
```bash
docker compose exec scheduler python -m skool.main --init-db
```

### 6.3 Create Admin Account

Create your initial administrative account using the CLI tool:

```bash
docker compose exec api python -m app.cli create-admin admin@yourdomain.com 'YourSecurePasswordHere123!'
```

---

## 7. SSL / TLS HTTPS Configuration

Choose one of three production SSL options:

### Option A: AWS Application Load Balancer + ACM (Recommended for EC2)

1. Request a free SSL certificate in **AWS Certificate Manager (ACM)** for `yourdomain.com`.
2. Create an **Application Load Balancer (ALB)** in the EC2 console:
   - HTTPS Listener on port `443` forwarding to your EC2 instance on port `80`.
   - HTTP Listener on port `80` with a redirect rule to HTTPS `443`.
   - Health check path set to `/api/health`.
3. Point your domain's DNS `A` (or `ALIAS`) record to the ALB DNS name.
4. **Benefit**: Auto-renewing certificates, zero certbot overhead on the EC2 host.

### Option B: Cloudflare Proxy (Fastest Setup for Lightsail & EC2)

1. Point your domain's nameservers to Cloudflare.
2. In Cloudflare DNS, set an `A` record pointing `yourdomain.com` to your server's Elastic IP with Proxy status enabled (Orange Cloud).
3. In Cloudflare SSL/TLS settings, set SSL mode to **Full** (or **Flexible**).
4. Cloudflare automatically provides free, managed Edge SSL certificates.

### Option C: Host Let's Encrypt Certbot with Nginx

If terminating SSL directly on the host without a load balancer:

1. Install Certbot on Ubuntu host:
   ```bash
   sudo apt-get install -y certbot python3-certbot-nginx
   ```
2. Stop port 80 temporarily or obtain certificate via standalone mode:
   ```bash
   sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com
   ```
3. Mount certificates into `/etc/nginx/certs` in `docker-compose.yml` and add port `443:443` mapping.

---

## 8. Automated Reboot Recovery (Systemd Service)

To guarantee the entire stack restarts automatically after server reboots, kernel updates, or crashes, configure a systemd service:

Create `/etc/systemd/system/skool-stack.service`:

```bash
sudo nano /etc/systemd/system/skool-stack.service
```

Paste the following definition:

```ini
[Unit]
Description=Skool Explorer Docker Compose Stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/skool
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
ExecReload=/usr/bin/docker compose restart
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable skool-stack.service
sudo systemctl status skool-stack.service
```

---

## 9. Automated Database Backups to AWS S3

Configure automated daily backups with Amazon S3 offsite storage.

### 9.1 Install and Configure AWS CLI

```bash
sudo apt-get install -y awscli

# Configure AWS IAM credentials with S3 PutObject permissions
aws configure
```

### 9.2 Create Nightly Backup Script

Create `/opt/skool/backup-db.sh`:

```bash
cat << 'EOF' > /opt/skool/backup-db.sh
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/tmp/skool-backups"
BUCKET_NAME="your-s3-backup-bucket-name"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/skool_${TIMESTAMP}.dump"

mkdir -p "${BACKUP_DIR}"

# Dump PostgreSQL database in custom compressed format
/usr/bin/docker compose -f /opt/skool/docker-compose.yml exec -T db \
    pg_dump -U skool -d skool -Fc > "${BACKUP_FILE}"

# Upload to S3
aws s3 cp "${BACKUP_FILE}" "s3://${BUCKET_NAME}/backups/skool_${TIMESTAMP}.dump"

# Remove local temporary dump
rm -f "${BACKUP_FILE}"

# Keep only last 30 days of backups in S3
echo "Database backup completed and uploaded to S3: skool_${TIMESTAMP}.dump"
EOF

chmod +x /opt/skool/backup-db.sh
```

### 9.3 Add Nightly Backup Cron Job

```bash
# Open crontab editor
crontab -e

# Run every night at 04:00 UTC
0 4 * * * /opt/skool/backup-db.sh >> /var/log/skool-backup.log 2>&1
```

---

## 10. Verification, Operations & Troubleshooting

### 10.1 Service Status & Health Verification

Check container statuses:
```bash
docker compose ps
```
*Expected*: All 4 containers (`skool-db`, `skool-api`, `skool-web`, `skool-scheduler`) running and healthy.

Test HTTP and API endpoints from the host:
```bash
# Frontend static HTML check
curl -I http://localhost/

# Health probe check via Nginx reverse proxy
curl http://localhost/api/health
```
*Expected response*:
```json
{"status":"ok","db":"up"}
```

### 10.2 Inspecting Service Logs

```bash
# View aggregated real-time logs
docker compose logs -f

# View backend API logs
docker compose logs -f api

# View scraper scheduler logs
docker compose logs -f scheduler

# View database logs
docker compose logs -f db

# View web server access & error logs
docker compose logs -f web
```

### 10.3 Triggering Recurring Harvester Jobs Manually

If you need to manually trigger scheduled jobs outside of their regular cron cycles:

```bash
# 1. Execute 3-Day Group Metrics Refresh immediately:
docker compose exec scheduler python -m skool.scheduler --run-now refresh

# 2. Execute Weekly Deep Discovery immediately:
docker compose exec scheduler python -m skool.scheduler --run-now discovery

# 3. Execute both jobs sequentially:
docker compose exec scheduler python -m skool.scheduler --run-now all
```

### 10.4 Updating the Application

To deploy code updates with zero downtime:

```bash
cd /opt/skool
git pull origin main
docker compose build
docker compose up -d --no-deps web api scheduler
```

### 10.5 Resource Monitoring

Check real-time CPU, RAM, and network I/O per container:

```bash
docker stats
```

---

## 11. Summary of Container Artifacts

| Component | Path | Description |
|---|---|---|
| **Frontend Dockerfile** | `Skool Frontend/client/Dockerfile` | Node 22 builder + Nginx 1.27 Alpine runner |
| **Nginx Configuration** | `Skool Frontend/client/nginx.conf` | Gzip compression, immutable asset caching, `/api/` reverse proxy |
| **Backend Dockerfile** | `Skool Backend/server-fastapi/Dockerfile` | Python 3.11-slim non-root user (UID 10001) + `/api/health` probe |
| **Scheduler Dockerfile** | `skool data/Dockerfile` | Python 3.11-slim runner executing `python -m skool.scheduler --daemon` |
| **Root Compose** | `docker-compose.yml` | 4-service stack (`web`, `api`, `db`, `scheduler`) |
| **Production Env** | `.env.production` | Production environment template with credentials |
| **Deployment Guide** | `AWS_DEPLOY.md` | Authoritative AWS launch and management manual |
