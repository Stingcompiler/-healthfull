# Install the clinic server — تركيب خادم المركز

Target: one mini PC on the clinic LAN running the Docker stack (`infra/docker-compose.yml`).
Time: about 2 hours. Works with no internet once images are on the machine.
Related: [backup-restore.md](backup-restore.md), [update-rollback.md](update-rollback.md).

## 1. Hardware and power — العتاد والكهرباء

| Item | Minimum | Recommended |
|---|---|---|
| Mini PC | 4 cores, 8 GB RAM, 256 GB SSD | 6-8 cores, 16 GB RAM, 512 GB NVMe SSD |
| Backup disk | second internal disk or USB disk, 1 TB | second internal SSD/HDD 1-2 TB, plus a rotated USB disk kept off-site |
| UPS | line-interactive, 650 VA, USB data port | 1000 VA+, 30+ minutes for server, switch and router |
| Network | gigabit switch, wired server | static IP for the server, Wi-Fi AP on the same LAN for tablets |

- BIOS: set "Restore on AC power loss" to **Power On**, so the server returns after a long power cut.
- Plug the server, switch and router into the UPS battery outlets; printers into surge-only outlets.
- Connect the UPS USB cable to the server (graceful shutdown, step 8).

## 2. Operating system — نظام التشغيل

Ubuntu Server 24.04 LTS, minimal install, OpenSSH enabled, user `clinicadmin`.

```bash
sudo timedatectl set-timezone Africa/Khartoum
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y unattended-upgrades curl git nut
sudo dpkg-reconfigure -plow unattended-upgrades          # security updates only
# Firewall: web from the LAN, SSH from the admin PC only
sudo ufw allow from 192.168.1.0/24 to any port 80,443 proto tcp
sudo ufw allow from 192.168.1.20 to any port 22 proto tcp
sudo ufw enable
```

**Firewall and Docker.** ufw does **not** protect ports published by Docker containers: Docker
writes its own iptables rules, which run before ufw's. The web container's ports would answer on
every interface, including a 4G/WAN link added later for cloud backups. Therefore set
`BIND_IP` in `.env` to the server's LAN address (step 6), e.g. `BIND_IP=192.168.1.10`, so the
system is published on the LAN interface only. Check after `up -d`:

```bash
sudo ss -ltnp | grep -E ':(80|443) '        # must show 192.168.1.10:80 / :443, not 0.0.0.0
```

For a stricter setup add rules to the `DOCKER-USER` chain (or use `ufw-docker`), e.g. allow only
`192.168.1.0/24` to the published ports.

Static IP: edit `/etc/netplan/*.yaml` (example `192.168.1.10/24`, gateway and DNS = router), then
`sudo netplan apply`. Name: add `hospital.lan -> 192.168.1.10` in the router's DNS/DHCP settings, or
in each workstation's hosts file.

## 3. Docker

Install Docker Engine and the compose plugin from Docker's apt repository
(https://docs.docker.com/engine/install/ubuntu/), then:

```bash
sudo usermod -aG docker clinicadmin && newgrp docker
docker compose version          # v2.24 or later
```

## 4. Disks and directories — الأقراص والمجلدات

```bash
# Second disk (check the device with lsblk). Format once, mount by UUID.
sudo mkfs.ext4 -L hospital-backup /dev/sdb1
sudo mkdir -p /srv/hospital
echo 'LABEL=hospital-backup /srv/hospital ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab
sudo mount -a
sudo mkdir -p /srv/hospital/backups /srv/hospital/pgbackrest
# Code
sudo mkdir -p /opt/hospital-sys && sudo chown clinicadmin: /opt/hospital-sys
git clone <repo-url> /opt/hospital-sys      # or unpack the release bundle there
```

## 5. Configuration — الإعدادات

```bash
cd /opt/hospital-sys
cp .env.example .env && chmod 600 .env
openssl rand -base64 48 | tr -d '\n/+=' ; echo     # run four times: POSTGRES_PASSWORD,
                                                   # DB_OWNER_PASSWORD, DB_APP_PASSWORD, DJANGO_SECRET_KEY
nano .env
```

Set at least: `POSTGRES_PASSWORD`, `DB_OWNER_PASSWORD`, `DB_APP_PASSWORD` (all three different),
`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`
(names/IPs typed in the browser plus `localhost,127.0.0.1`), `DJANGO_CSRF_TRUSTED_ORIGINS`
(the same, with `http://` or `https://`), `APP_IMAGE_TAG` (the release you install), and
`BIND_IP` = the server's LAN address (see "Firewall and Docker" in step 2).
Print `.env` and keep it in the clinic safe: without it, backups of secrets are lost.

### Database roles — أدوار قاعدة البيانات

The application never connects to PostgreSQL as an all-powerful account. Three roles exist:

| Role (`.env`) | Who uses it | What it can do |
|---|---|---|
| `POSTGRES_USER` (`hospital`) | db container, backup sidecar | everything (superuser): dumps, restores, pgBackRest |
| `DB_OWNER_USER` (`hospital_owner`) | `migrate` service, `infra/update.sh` | owns the database and every table: schema changes and the protection triggers |
| `DB_APP_USER` (`hospital_app`) | `app`, `maintenance` | read, insert, update and delete rows; nothing else |

Because the app role owns nothing, a bug or an attacker in the app cannot `TRUNCATE` a ledger
table, `ALTER` a table, or disable the triggers that keep approved invoices, closed shifts and the
ledger unchangeable (ADR 0006). The first start of the `db` container creates the two roles from
`.env` (`infra/db/initdb-roles.sh`); `infra/db-roles.sh` checks and repairs them at any time.
Role passwords: 16-128 characters from `A-Z a-z 0-9 . _ - ~` (the generator above qualifies).

## 6. Images and first start — الصور والتشغيل الأول

Pick one source of images:

```bash
infra/compose.sh build                                   # build on this machine (needs internet once)
docker load -i hospital-sys-v0.1.0.tar.gz                # offline: release archive from USB
infra/compose.sh pull                                    # from the registry in IMAGE_REGISTRY
```

Start and check:

```bash
infra/compose.sh up -d
infra/compose.sh ps -a                                   # db, app, web healthy; backup, maintenance up;
                                                         # migrate "Exited (0)"
curl -s http://192.168.1.10/api/ops/health               # BIND_IP: {"status": "ok", "db": "ok", ...}
infra/db-roles.sh                                        # roles and grants verified: "verified."
infra/compose.sh run --rm --no-deps app manage createsuperuser   # first system admin
```

Open `http://hospital.lan` from a workstation and log in. `up -d` first runs the one-off `migrate`
service: with `MIGRATE_ON_START=true` it creates the schema as the owner role, then exits, and only
then do `app` and `maintenance` start (as the app role). Later schema changes only go through
`infra/update.sh`. If `migrate` failed, `infra/compose.sh logs migrate` says why and the app stays
down until it succeeds.

The `maintenance` service (app image) runs `manage.py maintenance` at start and then daily: it
deletes expired sessions and stale login-throttle rows, which would otherwise pile up in the
database and in every backup. Run it by hand with
`infra/compose.sh run --rm --no-deps app manage maintenance`.

## 7. Prove the backups work — تأكيد النسخ الاحتياطي

```bash
infra/compose.sh run --rm --no-deps -T backup /opt/backup/backup-nightly.sh
infra/compose.sh run --rm --no-deps -T backup /opt/backup/restore-test.sh
tail -n 1 /srv/hospital/backups/status/restore-tests.jsonl    # "status":"ok"
```

The sidecar then runs the backup nightly at `BACKUP_TIME` and a restore test monthly.
Optional continuous WAL archiving and cloud copies: [backup-restore.md](backup-restore.md#enable-pgbackrest).

## 8. UPS shutdown (NUT) — الإيقاف الآمن عند انقطاع الكهرباء

```bash
sudo nut-scanner -U                               # find the UPS; copy the block into ups.conf
sudoedit /etc/nut/ups.conf                        # [clinicups] driver=usbhid-ups port=auto
sudoedit /etc/nut/nut.conf                        # MODE=standalone
sudoedit /etc/nut/upsd.users                      # [upsmon] password=<random> upsmon primary
sudoedit /etc/nut/upsmon.conf                     # MONITOR clinicups@localhost 1 upsmon <random> primary
sudo systemctl restart nut-server nut-monitor
upsc clinicups@localhost battery.charge
```

On low battery NUT shuts the server down; Docker stops PostgreSQL cleanly (60 s grace). When power
returns, the BIOS setting powers the server on and `restart: unless-stopped` brings the stack back.

## 9. Internal TLS (optional) — اتصال مشفر داخل الشبكة

1. In `.env`: `CADDY_SITE_ADDRESS=hospital.lan, 192.168.1.10`, `DJANGO_SECURE_COOKIES=1`,
   `DJANGO_CSRF_TRUSTED_ORIGINS=https://hospital.lan,https://192.168.1.10`.
2. `infra/compose.sh up -d web app`
3. Export the clinic root certificate and install it on every workstation and tablet:
   `infra/compose.sh cp web:/var/lib/caddy/data/caddy/pki/authorities/local/root.crt ./hospital-root-ca.crt`
   - Windows: double-click, Install Certificate, Local Machine, "Trusted Root Certification Authorities".
   - Android: Settings, Security, Encryption & credentials, Install a certificate, CA certificate.
4. Browse to `https://hospital.lan`. The root lasts 10 years; Caddy renews the server certificate
   itself. Keep the `caddy_data` volume: deleting it creates a new root to distribute.

## 10. Workstations — أجهزة العمل

- Chrome or Edge, bookmark `http://hospital.lan`, set the page zoom per screen size.
- Receipt and label printers: install the device agent per [agent/README.md](../../agent/README.md);
  add the web app's origin to its `allowed_origins`.

## Checklist — قائمة التحقق

- [ ] BIOS power-on after AC loss; UPS shuts the server down (test by pulling the plug)
- [ ] `.env` filled, printed, stored in the safe
- [ ] `infra/compose.sh ps` all healthy; login works from a workstation
- [ ] `infra/db-roles.sh` ends with "verified."
- [ ] Manual backup and restore test both `ok`
- [ ] Off-site USB rotation scheduled (backup-restore.md)
