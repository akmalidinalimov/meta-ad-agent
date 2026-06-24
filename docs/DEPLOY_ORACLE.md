# Deploy the agent 24/7 on an Oracle Cloud "Always Free" VM ($0)

The agent needs one small **always-on** container (the scheduler loops every 4h/daily and stores its
data as files). Oracle's Always Free tier runs that at no cost. `docker compose up -d --build` brings up
the app behind Caddy, with `restart: unless-stopped` so it survives crashes and reboots.

Two stages: **Stage 1** gets it always-on over HTTP (suggestions already flow to Telegram; approve in the
web UI). **Stage 2** adds free HTTPS so the Telegram Approve/Reject buttons work and the console is private.

---

## Stage 1 — always-on over HTTP (~15 min)

### 1. Create the VM
- In the Oracle Cloud console: **Compute → Instances → Create instance**.
- **Shape:** change to **Ampere (Arm) → VM.Standard.A1.Flex**, 1–2 OCPU / 6–12 GB RAM (within Always Free).
  (The `node:20`/`python:3.12` images are multi-arch, so they build fine on Arm; ≥6 GB avoids an npm-build OOM.)
- **Image:** Canonical **Ubuntu 22.04**.
- **SSH keys:** download/save the private key.
- After it boots, **reserve a static public IP** (Networking → the instance's VNIC → edit the public IP →
  "Reserved") so the address doesn't change on stop/start. Note the IP.

### 2. Open the ports (two places — the #1 Oracle gotcha)
**a) Cloud firewall (VCN Security List):** Networking → your VCN → Security Lists → default → add
**Ingress** rules: Source `0.0.0.0/0`, IP protocol TCP, destination ports **80** and **443**.

**b) OS firewall (Oracle's Ubuntu blocks non-22 ports by default):** SSH in (next step) then run:
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

### 3. SSH in + install Docker
```bash
ssh -i /path/to/your-key ubuntu@<YOUR_VM_IP>

# Docker Engine + compose plugin
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
newgrp docker   # or log out/in so docker works without sudo
```

### 4. Get the code + secrets
```bash
git clone https://github.com/akmalidinalimov/meta-ad-agent.git
cd meta-ad-agent
git checkout feat/review-improvements

nano .env     # paste the variables below, then Ctrl-O, Enter, Ctrl-X
chmod 600 .env
```
Minimum `.env` (copy values from your local `.env`):
```env
REASONING_PROVIDER=anthropic
ANTHROPIC_MODEL=claude-opus-4-8
ANTHROPIC_API_KEY=sk-ant-...
META_ACCESS_TOKEN=...
META_APP_ID=...
META_AD_ACCOUNT_ID=act_668405878867091
META_BUSINESS_ID=...
META_API_VERSION=v23.0
META_PIXEL_ID=
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ADMIN_CHAT_ID=...
TELEGRAM_COMMAND_SECRET=...
TELEGRAM_ALLOWED_CHAT_IDS=...
TELEGRAM_ALLOWED_USER_IDS=...
BITRIX24_WEBHOOK_URL=...
BITRIX24_WEBHOOK_KEY=...
OPENAI_API_KEY=
MONITORING_SCHEDULER_ENABLED=true
META_LIVE_WRITES_ENABLED=false
```

### 5. Launch
```bash
docker compose up -d --build      # first build takes a few minutes
docker compose logs -f app        # watch startup; Ctrl-C to stop watching
```
Check it: open `http://<YOUR_VM_IP>/api/health` → `{"status":"ok"}`, and `http://<YOUR_VM_IP>/` for the UI.
The scheduler is now running (opportunities daily, monitoring 4-hourly). Suggestions arrive in Telegram;
approve them in the web UI for now (Telegram buttons come in Stage 2).

---

## Stage 2 — free HTTPS + lock the console (~15 min)

### 6. Free domain (DuckDNS)
- Go to **duckdns.org**, sign in, create a subdomain (e.g. `youragent`), and set its IP to your VM's
  static IP → you now have `youragent.duckdns.org`.

### 7. Turn on HTTPS
Add one line to `.env` and point CORS at the domain:
```bash
echo "SITE_ADDRESS=youragent.duckdns.org" >> .env
# also set/replace this line in .env:
#   FUNNEL_ALLOWED_ORIGINS=https://youragent.duckdns.org
docker compose up -d            # Caddy auto-fetches a Let's Encrypt cert
```
Check `https://youragent.duckdns.org/api/health`.

### 8. Register the Telegram webhook (enables Approve/Reject buttons)
```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://youragent.duckdns.org/api/telegram/command&secret_token=<TELEGRAM_COMMAND_SECRET>"
```
(Replace the two values from your `.env`. Expect `{"ok":true,...}`.)

### 9. Lock the console
Edit `Caddyfile`, uncomment the `basic_auth` block, and set a password:
```bash
docker compose exec caddy caddy hash-password --plaintext 'choose-a-password'
# paste the printed hash into the Caddyfile basic_auth block, then:
docker compose up -d
```
(On older Caddy the directive is `basicauth`; on 2.7+ it's `basic_auth`.)

### 10. Re-sync the account
Open the UI (or `POST /api/meta/sync`) and run a fresh sync so the proactive suggestions start mirroring
your winning campaigns' settings.

---

## Day-to-day
```bash
docker compose logs -f app        # live logs
docker compose restart app        # restart just the app
git pull && docker compose up -d --build   # deploy the latest code
docker compose down               # stop everything (data persists in volumes)
```
Reboot test: `sudo reboot` → after it comes back, `docker compose ps` shows the containers running again
(that's the always-on guarantee). Live writes stay OFF (`META_LIVE_WRITES_ENABLED=false`) until you choose
to enable them.
