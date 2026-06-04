# Deploy GoldLoan as a free global demo (Oracle Cloud Always Free)

This hosts the full stack — Django + MySQL + Redis + Celery worker + Celery
beat + WeasyPrint — on **one free VM**, reachable worldwide over HTTPS, with
**working tenant subdomains** and **no domain to buy**.

The subdomain trick: we use [`sslip.io`](https://sslip.io), a free wildcard
DNS service. `anything.<YOUR-IP-with-dashes>.sslip.io` automatically resolves
to `<YOUR-IP>`. So `varaahi.152-67-10-20.sslip.io` just works. Caddy then
issues a free Let's Encrypt cert per subdomain automatically (on-demand TLS).

> Replace `152.67.10.20` everywhere below with your VM's real public IP, and
> note its dashed form `152-67-10-20`.

---

## 1. Create the free VM

1. Sign up at <https://cloud.oracle.com> (card required for identity, **not
   charged** on Always Free).
2. **Compute → Instances → Create instance.**
   - Image: **Ubuntu 22.04**
   - Shape: **VM.Standard.A1.Flex (Ampere/ARM)** — set 2 OCPU / 12 GB (still
     free; max free is 4/24).
   - Add your SSH public key.
3. **Networking → VCN → Security List → add Ingress rules** for the public
   subnet: allow TCP **80** and **443** from `0.0.0.0/0`.
4. SSH in: `ssh ubuntu@152.67.10.20`

Also open the OS firewall:
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

---

## 2. System packages

```bash
sudo apt update && sudo apt -y upgrade
sudo apt install -y python3-venv python3-dev build-essential git \
  mysql-server redis-server \
  libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
  libffi-dev shared-mime-info        # WeasyPrint runtime libs

# Caddy (automatic HTTPS reverse proxy)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

---

## 3. Database

```bash
sudo mysql <<'SQL'
CREATE DATABASE goldloan CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'goldloan'@'localhost' IDENTIFIED BY 'CHANGE_ME_strong_pw';
GRANT ALL PRIVILEGES ON goldloan.* TO 'goldloan'@'localhost';
FLUSH PRIVILEGES;
SQL
```

---

## 4. App code + venv

```bash
sudo mkdir -p /var/www && sudo chown ubuntu:ubuntu /var/www
cd /var/www
git clone <your-repo-url> goldloan   # or scp the folder up
cd goldloan

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

---

## 5. Production `.env`

Create `/var/www/goldloan/.env`:

```ini
DJANGO_SECRET_KEY=<paste 50+ random chars>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=.152-67-10-20.sslip.io
CSRF_TRUSTED_ORIGINS=https://*.152-67-10-20.sslip.io
TENANT_BASE_DOMAIN=152-67-10-20.sslip.io

DB_NAME=goldloan
DB_USER=goldloan
DB_PASSWORD=CHANGE_ME_strong_pw
DB_HOST=127.0.0.1
DB_PORT=3306

CELERY_BROKER_URL=redis://127.0.0.1:6379/1
CELERY_RESULT_BACKEND=django-db

NOTIFICATION_CHANNEL=log
SITE_BASE_URL=https://152-67-10-20.sslip.io
GOLDRATE_CITY=hyderabad
```

Generate a secret key:
```bash
.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

---

## 6. Migrate, seed, collect static

```bash
cd /var/www/goldloan
export DJANGO_SETTINGS_MODULE=config.settings.prod
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_superadmin
.venv/bin/python manage.py collectstatic --noinput
# onboard a demo broker so a tenant subdomain exists:
.venv/bin/python manage.py onboard_tenant \
  --name "Varaahi Gold Finance" --slug varaahi \
  --owner-username admin --owner-email owner@varaahi.local \
  --owner-password 'Varaahi@2026!' --phone 9876543210
```

---

## 7. systemd services (gunicorn + celery worker + beat)

**`/etc/systemd/system/goldloan-web.service`**
```ini
[Unit]
Description=GoldLoan Gunicorn
After=network.target mysql.service

[Service]
User=ubuntu
WorkingDirectory=/var/www/goldloan
Environment=DJANGO_SETTINGS_MODULE=config.settings.prod
ExecStart=/var/www/goldloan/.venv/bin/gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/goldloan-worker.service`**
```ini
[Unit]
Description=GoldLoan Celery worker
After=network.target redis-server.service mysql.service

[Service]
User=ubuntu
WorkingDirectory=/var/www/goldloan
Environment=DJANGO_SETTINGS_MODULE=config.settings.prod
ExecStart=/var/www/goldloan/.venv/bin/celery -A config worker -l info
Restart=always

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/goldloan-beat.service`**
```ini
[Unit]
Description=GoldLoan Celery beat
After=network.target redis-server.service mysql.service

[Service]
User=ubuntu
WorkingDirectory=/var/www/goldloan
Environment=DJANGO_SETTINGS_MODULE=config.settings.prod
ExecStart=/var/www/goldloan/.venv/bin/celery -A config beat -l info \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable them:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now goldloan-web goldloan-worker goldloan-beat
sudo systemctl status goldloan-web   # confirm it's running
```

---

## 8. Caddy — automatic HTTPS for every tenant subdomain

**`/etc/caddy/Caddyfile`** (handles the base host + any `*.sslip.io` tenant):
```caddy
{
    # Issue certs on demand for tenant subdomains we don't list explicitly.
    on_demand_tls {
        interval 2m
        burst    5
    }
}

152-67-10-20.sslip.io, *.152-67-10-20.sslip.io {
    tls {
        on_demand
    }

    # Tenant logos & other uploads (MEDIA_ROOT). Django does NOT serve these
    # when DEBUG=False, and WhiteNoise only serves static — so Caddy serves
    # /media/* straight from disk.
    handle_path /media/* {
        root * /var/www/goldloan/media
        file_server
    }

    # Everything else → the app.
    reverse_proxy 127.0.0.1:8000 {
        header_up X-Forwarded-Proto https
    }
}
```

> Static files (`/static/`) are served by WhiteNoise inside the app, so they
> need no Caddy rule — but **uploads (`/media/`) do**, hence the block above.

```bash
sudo systemctl restart caddy
sudo journalctl -u caddy -f      # watch the first cert issue
```

> Caddy fetches a Let's Encrypt cert the first time each subdomain is hit, so
> the very first request to a new tenant may take a few seconds.

---

## 9. Visit it

| URL | Who | Login |
|-----|-----|-------|
| `https://152-67-10-20.sslip.io/admin/` | Super-admin | `superadmin / Admin@2026!` |
| `https://varaahi.152-67-10-20.sslip.io/admin/` | Varaahi broker | `admin / Varaahi@2026!` |

That's a globally reachable, HTTPS, multi-tenant demo — **₹0/month, no domain
purchased.**

---

## Upgrading to a real domain later
When you outgrow the demo, buy a domain and:
1. Add DNS: `A  @ → IP` and `A  *.yourdomain.com → IP` (wildcard).
2. In `.env` set `TENANT_BASE_DOMAIN=yourdomain.com`,
   `DJANGO_ALLOWED_HOSTS=.yourdomain.com`,
   `CSRF_TRUSTED_ORIGINS=https://*.yourdomain.com`.
3. Swap the hostnames in the `Caddyfile`. Restart `goldloan-web` and `caddy`.

## Handy ops
```bash
# redeploy after code changes
cd /var/www/goldloan && git pull
.venv/bin/pip install -r requirements.txt
DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py migrate
DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart goldloan-web goldloan-worker goldloan-beat

# logs
sudo journalctl -u goldloan-web -f
```
