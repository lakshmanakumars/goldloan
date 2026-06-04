# GoldLoan SaaS

Multi-tenant gold loan management platform for pawn brokers (India / NBFC).
Each broker is onboarded as a **tenant** by the platform super-admin and gets
their own subdomain back-office to manage customers, gold loans, repayments,
and monthly interest reminders.

## Stack

- Python 3.10+, Django 5.0
- MySQL 8 (system install)
- Redis (for Celery broker + result backend)
- Celery + Celery Beat (monthly reminders)
- Django Unfold (modern admin theme)
- django-money (₹ INR money fields)
- django-auditlog (change tracking)
- WeasyPrint (PDF generation, ready for pledge tickets)

## Architecture

Shared-schema multi-tenancy:

- One MySQL database, every tenant-scoped table has a `tenant_id` column.
- A subdomain-driven middleware (`apps.core.middleware.TenantMiddleware`)
  resolves the tenant per request and stashes it in thread-local storage.
- All tenant-scoped models inherit `apps.core.models.TenantAwareModel`,
  which exposes a manager that auto-filters every query by the current
  tenant and auto-populates `tenant_id` on save.
- Super-admin requests have no tenant set, so queries are unfiltered —
  used only by platform staff to manage the tenant catalog.

```
URL                                 Who                            Tenant set?
admin.localhost:8765/admin/         Platform super-admin           No
localhost:8765/admin/               Platform super-admin           No
varaahi.localhost:8765/admin/       Varaahi staff (broker)         Yes (varaahi)
foo.localhost:8765/admin/           Unknown subdomain              404
```

## Modular app layout

```
config/                    Project settings, urls, celery
apps/
  core/                    TenantMiddleware, TenantAwareModel, thread-local
  iam/                     Tenant, custom User, onboard_tenant command
  customers/               Customer + KYC fields
  loans/                   Loan, GoldItem, Repayment, interest calc
  notifications/           InterestReminder + Celery task + senders
```

Each app is a candidate to be lifted into its own service later
(microservices off-ramp). Today they all live in one process.

## Local setup

Prereqs already done in this checkout:
- `.venv/` with all deps installed
- MySQL database `goldloan`, user `goldloan@localhost`
- Migrations applied
- Super-admin `superadmin / Admin@2026!` seeded
- Sample tenant `varaahi` (Varaahi Gold Finance) with owner `admin / Varaahi@2026!`

If you start fresh (different machine), run:

```bash
cd /var/www/html/goldloan

# 1. venv (workaround if python3-venv apt pkg is missing)
python3 -m venv --without-pip .venv
curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python

# 2. install deps
.venv/bin/pip install -r requirements.txt

# 3. MySQL DB + user (run as MySQL root)
mysql -uroot -p <<'SQL'
CREATE DATABASE goldloan CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'goldloan'@'localhost' IDENTIFIED BY 'Goldloan@Dev2026!';
GRANT ALL PRIVILEGES ON goldloan.* TO 'goldloan'@'localhost';
FLUSH PRIVILEGES;
SQL

# 4. copy env and migrate
cp .env.example .env  # then edit DB_PASSWORD etc.
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_superadmin

# 5. onboard a sample tenant
.venv/bin/python manage.py onboard_tenant \
  --name "Varaahi Gold Finance" --slug varaahi \
  --owner-username admin --owner-email owner@varaahi.local \
  --owner-password 'Varaahi@2026!' --phone 9876543210
```

## Running

```bash
# Dev server (port 8765 because 8000 is taken on this box)
.venv/bin/python manage.py runserver 0.0.0.0:8765
```

Visit:

| URL                                       | Who                              |
|-------------------------------------------|----------------------------------|
| http://localhost:8765/                    | Super-admin landing              |
| http://localhost:8765/admin/              | Super-admin Django/Unfold        |
| http://varaahi.localhost:8765/            | Varaahi tenant landing           |
| http://varaahi.localhost:8765/admin/      | Varaahi back-office              |

Login credentials seeded:

| Host                       | Username      | Password         |
|----------------------------|---------------|------------------|
| localhost                  | superadmin    | Admin@2026!      |
| varaahi.localhost          | admin         | Varaahi@2026!    |

`*.localhost` resolves to 127.0.0.1 automatically on modern Linux — no
`/etc/hosts` edit needed.

## Onboarding a new pawn broker tenant

Two ways:

**A) Via super-admin UI** — log in at `http://localhost:8765/admin/` →
*Pawn Brokers (Tenants)* → Add. Then create a user, set `tenant` to the
new broker, tick `is_tenant_owner` and `is_staff`.

**B) Via CLI (idempotent, scriptable):**

```bash
.venv/bin/python manage.py onboard_tenant \
  --name "Sunrise Jewellers" --slug sunrise \
  --owner-username sunrise_owner \
  --owner-email owner@sunrise.local \
  --owner-password 'Sunrise@2026!' \
  --phone 9988776655 \
  --license-no "PB-MH-2024-9988" \
  --gst-no "27AAAAA0000A1Z5" \
  --plan starter
```

The owner can immediately log in at `http://sunrise.localhost:8765/admin/`.

## Running the monthly reminder job

Two modes:

**Manual / one-off (no broker required):**

```bash
.venv/bin/python manage.py shell -c "
from apps.notifications.tasks import send_monthly_interest_reminders
print(send_monthly_interest_reminders.apply().get())
"
```

**Production schedule (Celery Beat — 09:00 IST on the 1st of every month):**

```bash
# in three separate terminals
.venv/bin/celery -A config worker -l info
.venv/bin/celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Reminders are persisted as `notifications.InterestReminder` rows with
status `pending → sent / failed`. Re-running the same month is idempotent
because of the unique constraint on `(loan, period_month, channel)`.

## Notification senders

`NOTIFICATION_CHANNEL` env var picks the implementation:

| Value             | Behaviour                             |
|-------------------|---------------------------------------|
| `log` (default)   | Just logs to console (dev/test)       |
| `msg91`           | SMS via MSG91 (stub — fill in client) |
| `whatsapp_cloud`  | WhatsApp Cloud API (stub)             |

Real provider clients live in `apps/notifications/services.py`.

## Smoke test

```bash
.venv/bin/python manage.py shell < scripts/smoke_test.py
```

Creates one customer + one loan in the varaahi tenant, runs the reminder task,
prints the resulting InterestReminder row.

## What's next

Phase 2 (not yet built):
- Gold rate master + LTV calculator (RBI 75 % cap)
- Pledge ticket PDF (WeasyPrint, bilingual)
- Repayment receipt + statement printing
- NPA classification + auction notice workflow (RBI 14-day rule)
- Double-entry ledger module (own DB once extracted)
- WhatsApp + MSG91 real client implementations
- Razorpay subscription billing for SaaS plans
- Custom-domain support per tenant
- Self-service tenant signup + 2FA

## Known limitations of v1

- Reminder message is hard-coded English. Add template per-tenant for
  regional language.
- No row-level locking on loan numbering — fine for low concurrency,
  add `SELECT ... FOR UPDATE` before scaling.
- Tenant onboarding doesn't send a welcome email yet.
- `static/` folder is empty; collectstatic only pulls Unfold + admin
  assets. Add brand assets per tenant later.
