# Deploy AegisAgent API on NeevCloud + Cloudflare Pages

Host the **FastAPI backend** on a NeevCloud CPU VM (Gemini calls go outbound; no GPU needed).  
Host the **static UI** on Cloudflare Pages (`web/`). Connect them with HTTPS via **Cloudflare Tunnel** (recommended) or a reverse proxy.

```
┌─────────────────────┐         HTTPS          ┌──────────────────────┐
│  Cloudflare Pages   │  ──── fetch /pipeline ─▶│  NeevCloud CPU VM    │
│  (web/ static UI)   │                         │  uvicorn :8080       │
└─────────────────────┘                         │  Chroma + FastAPI    │
         │                                      └──────────┬───────────┘
         │                                                 │
         │              optional Cloudflare Tunnel         │
         └──────────────── api.yourdomain.com ────────────┘
                                    │
                                    ▼
                          Google Gemini API (planner + auditor)
```

## Why this stack

| Piece | Where | Notes |
|-------|--------|--------|
| UI | Cloudflare Pages | Free CDN, global, no Python |
| API | NeevCloud CPU VM | Always-on, no Render cold starts |
| LLM | Gemini (API key on VM) | No GPU VM required |
| RAG | Chroma on VM disk | Auto-ingests fixtures on first boot |

**Suggested VM:** **NanoBoost** — 2 vCPU / 4 GB RAM (~₹939/mo).  
₹15,000 credits ≈ **15+ months** of always-on API hosting.

Docs: [NeevCloud VM getting started](https://docs.ai.neevcloud.com/vm-service/getting-started) · [CPU pricing](https://neevcloud.com/cpu-pricing)

---

## Part 1 — NeevCloud VM

### 1. Create the instance

1. Log in at [my.neevcloud.com](https://my.neevcloud.com).
2. **New VM** → **CPU VM** (not GPU).
3. **Image:** Ubuntu 24.04 LTS.
4. **Size:** NanoBoost (2 vCPU / 4 GB) or larger if you run other services.
5. **Network:** Public IPv4 (needed for SSH; tunnel option below avoids opening HTTP to the world).
6. **SSH key:** Add your public key.
7. **Firewall / security group:** Allow **TCP 22** (SSH).  
   - With Cloudflare Tunnel: **do not** expose 8080 publicly.  
   - Without tunnel: allow **TCP 80/443** and use Caddy (see [Alternative: Caddy + public IP](#alternative-caddy--public-ip)).
8. Deploy and note the **public IP**.

### 2. SSH in and run bootstrap

```bash
ssh ubuntu@YOUR_VM_IP
```

Clone the repo and run the setup script (installs Python, venv, systemd unit):

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/anishreddy3/aegis-agent.git /opt/aegis-agent
# Or your fork:
# sudo git clone https://github.com/YOU/aegis-agent.git /opt/aegis-agent

cd /opt/aegis-agent
sudo bash deploy/neevcloud/setup-api.sh
```

The script:

- Creates system user `aegis`
- Installs Python 3 + venv deps
- Installs Python packages from `requirements.txt`
- Installs `aegis-api.service` under systemd
- Creates `/opt/aegis-agent/.env` from template if missing

### 3. Configure production environment

```bash
sudo nano /opt/aegis-agent/.env
```

Minimum for live demo:

```bash
GOOGLE_API_KEY=your_real_key
DEMO_MODE=false
GEMINI_MODEL=gemini-3.6-flash
GEMINI_PARANOID_MODEL=gemini-3.1-pro-preview
GEMINI_PARANOID_FAST_MODEL=gemini-3.6-flash
CORS_ORIGINS=https://aegis-agent.pages.dev,https://your-custom-domain.com
API_HOST=0.0.0.0
API_PORT=8080
```

Use your real Cloudflare Pages URL(s) in `CORS_ORIGINS` (comma-separated, no spaces).  
See `deploy/neevcloud/env.production.example` for the full list.

Secure the file:

```bash
sudo chown aegis:aegis /opt/aegis-agent/.env
sudo chmod 600 /opt/aegis-agent/.env
```

### 4. Start the API

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aegis-api
sudo systemctl status aegis-api
```

Verify locally on the VM:

```bash
curl -s http://127.0.0.1:8080/health | python3 -m json.tool
```

Logs:

```bash
journalctl -u aegis-api -f
```

### 5. Update after code changes

```bash
cd /opt/aegis-agent
sudo -u aegis git pull
sudo -u aegis /opt/aegis-agent/.venv/bin/pip install -r requirements.txt
sudo systemctl restart aegis-api
```

---

## Part 2 — Cloudflare Tunnel (recommended)

Cloudflare Tunnel gives you `https://api.yourdomain.com` → `localhost:8080` without opening port 8080 on the VM.

### Prerequisites

- Domain on Cloudflare (free plan is fine).
- Pages project for the UI (same zone is convenient).

### 1. Create the tunnel (Cloudflare Zero Trust dashboard)

1. [Cloudflare Zero Trust](https://one.dash.cloudflare.com/) → **Networks** → **Tunnels** → **Create a tunnel**.
2. Name: `aegis-api`.
3. Install connector — copy the `cloudflared` install command for **Linux amd64**.
4. On the VM:

```bash
# Run Cloudflare's install command, then authenticate the tunnel
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb

sudo cloudflared tunnel login
sudo cloudflared tunnel create aegis-api
```

Note the tunnel UUID from the create output.

### 2. Install config

```bash
sudo mkdir -p /etc/cloudflared
sudo cp /opt/aegis-agent/deploy/neevcloud/cloudflared-config.yml.example /etc/cloudflared/config.yml
sudo nano /etc/cloudflared/config.yml
```

Replace:

- `TUNNEL_UUID` → your tunnel ID
- `api.yourdomain.com` → your API hostname

Credentials file path is usually `/root/.cloudflared/TUNNEL_UUID.json` — copy to `/etc/cloudflared/`:

```bash
sudo cp ~/.cloudflared/TUNNEL_UUID.json /etc/cloudflared/
sudo chmod 600 /etc/cloudflared/TUNNEL_UUID.json
```

### 3. Route DNS (Cloudflare dashboard)

In the tunnel setup UI, add a **Public Hostname**:

| Field | Value |
|-------|--------|
| Subdomain | `api` |
| Domain | `yourdomain.com` |
| Service | `http://localhost:8080` |

Or via CLI:

```bash
sudo cloudflared tunnel route dns aegis-api api.yourdomain.com
```

### 4. Run cloudflared as a service

```bash
sudo cp /opt/aegis-agent/deploy/neevcloud/cloudflared.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

Test from your laptop:

```bash
curl -s https://api.yourdomain.com/health | python3 -m json.tool
```

---

## Part 3 — Cloudflare Pages (UI)

From your **local machine** (repo root):

```bash
npx wrangler login
make pages-deploy
```

After deploy:

1. Open `https://aegis-agent.pages.dev` (or your custom domain).
2. Set **API URL** to `https://api.yourdomain.com` (saved in browser `localStorage`).
3. Confirm `CORS_ORIGINS` on the VM includes your Pages origin.

Optional: bake the default API URL into `web/app.js` before deploy:

```javascript
$("apiUrl").value = saved || "https://api.yourdomain.com";
```

---

## Alternative: Caddy + public IP

If you skip Cloudflare Tunnel, put Caddy in front of uvicorn on the VM public IP.

```bash
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update && sudo apt-get install -y caddy

sudo cp /opt/aegis-agent/deploy/neevcloud/Caddyfile.example /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile   # set api.yourdomain.com
sudo systemctl reload caddy
```

Point Cloudflare DNS **A record** for `api` → VM public IP (orange cloud on for free SSL at edge, or Caddy handles Let's Encrypt on grey cloud).

Open firewall: **80**, **443**.

---

## Demo checklist (before judges)

1. **Warm the API:** `curl https://api.yourdomain.com/health`
2. **Run one full pipeline** from Pages (Pro audit can take 60–80s).
3. **Enable Fast audit** in the UI if Pro latency is too slow live.
4. **Do not** commit `.env` or expose `GOOGLE_API_KEY` in Pages.

### Test staged pipeline

```bash
API=https://api.yourdomain.com

curl -s -X POST "$API/pipeline/plan" \
  -H 'Content-Type: application/json' \
  -d '{"query":"Transfer 1 USDC to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"}' \
  | python3 -m json.tool
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `502` from Cloudflare Tunnel | `systemctl status aegis-api` — API must listen on `127.0.0.1:8080` |
| CORS error in browser | Add exact Pages URL to `CORS_ORIGINS` (scheme + host, no trailing slash) |
| `[DEMO]` in reasoning | `GOOGLE_API_KEY` missing/invalid or `DEMO_MODE=true` |
| Chroma empty after reboot | Normal on ephemeral disk — API re-ingests on startup; check logs for `ingest` |
| Pro audit timeout | UI allows 120s; enable **Fast audit** or retry |
| `503` on gemini-3.7-flash | Expected under load — fallback uses `gemini-3.6-flash` |
| Out of memory | Upgrade to 4 GB+ or disable Streamlit on the same VM |

### Useful commands

```bash
# API service
sudo systemctl restart aegis-api
journalctl -u aegis-api -n 100 --no-pager

# Tunnel
sudo systemctl restart cloudflared
journalctl -u cloudflared -n 50 --no-pager

# Re-ingest RAG manually
curl -X POST http://127.0.0.1:8080/reingest
```

---

## Files in this directory

| File | Purpose |
|------|---------|
| `README.md` | This guide |
| `setup-api.sh` | First-time VM bootstrap |
| `aegis-api.service` | systemd unit for uvicorn |
| `env.production.example` | Production `.env` template |
| `cloudflared-config.yml.example` | Tunnel ingress config |
| `cloudflared.service` | systemd unit for cloudflared |
| `Caddyfile.example` | Optional reverse proxy |

---

## Security notes

- Keep `GOOGLE_API_KEY` and `PRIVATE_KEY` only on the VM `.env` (mode `600`).
- Prefer **Cloudflare Tunnel** over exposing `:8080` on a public IP.
- Never use a mainnet wallet private key in hackathon demos.
- Rotate keys if `.env` is ever leaked.
