# No custom domain — Cloudflare Quick Tunnel + Pages

Use this when you **don't own a domain**. You get a free public HTTPS URL from Cloudflare (`*.trycloudflare.com`) that forwards to your NeevCloud API. Your UI stays on **`*.pages.dev`**.

```
Browser  →  https://aegis-agent.pages.dev     (Cloudflare Pages — static UI)
         →  https://random.trycloudflare.com   (Quick Tunnel — API on NeevCloud)
         →  http://127.0.0.1:8080              (uvicorn on VM)
```

**No paid plan required** for this path (Pages free + Quick Tunnel free).

> **Note:** The `trycloudflare.com` URL **changes when the tunnel restarts**. After reboot, run `cat /var/log/aegis-tunnel.url` and update the API URL in the Pages UI (or redeploy with a baked-in default).

---

## Step 1 — API running on NeevCloud

SSH into the VM:

```bash
sudo systemctl enable --now aegis-api
curl -s http://127.0.0.1:8080/health
```

Ensure `.env` has:

```bash
GOOGLE_API_KEY=...
DEMO_MODE=false
CORS_ORIGINS=https://aegis-agent.pages.dev
```

Use your real Pages URL once you know it (see Step 3). Multiple origins: comma-separated, no spaces.

---

## Step 2 — Start Quick Tunnel on the VM

```bash
cd /opt/aegis-agent
git pull   # get start-quick-tunnel.sh if missing
sudo bash deploy/neevcloud/start-quick-tunnel.sh --install-service
```

Wait ~15 seconds, then:

```bash
cat /var/log/aegis-tunnel.url
# Example: https://abc-def-123.trycloudflare.com
curl -s "$(cat /var/log/aegis-tunnel.url)/health"
```

Copy that URL — this is your **public API base URL**.

### If the URL file is empty

```bash
sudo journalctl -u cloudflared-quick -n 50 --no-pager | grep trycloudflare
```

---

## Step 3 — Deploy Cloudflare Pages (from your Mac)

```bash
cd ~/Projects/aegis-agent   # or your clone path
npx wrangler login
make pages-deploy
```

Note your Pages URL, e.g. `https://aegis-agent.pages.dev`.

**Update CORS on the VM** if you used a placeholder:

```bash
sudo nano /opt/aegis-agent/.env
# CORS_ORIGINS=https://aegis-agent.pages.dev
sudo systemctl restart aegis-api
```

---

## Step 4 — Connect UI to API

1. Open your Pages URL in the browser.
2. In **API URL**, paste: `https://xxxx.trycloudflare.com` (from Step 2, no trailing slash).
3. Run **Valid transfer** demo.

The URL is saved in browser `localStorage` for next visits.

### Optional: bake default API URL before deploy

Edit `web/app.js` → `defaultApiUrl()` and set your tunnel URL, then `make pages-deploy` again.

---

## Step 5 — Demo checklist

```bash
# On VM
curl -s "$(cat /var/log/aegis-tunnel.url)/health"
curl -s -X POST "$(cat /var/log/aegis-tunnel.url)/pipeline/plan" \
  -H 'Content-Type: application/json' \
  -d '{"query":"Transfer 1 USDC to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"}'
```

In the UI:

- [ ] No `[DEMO]` in planner reasoning (live Gemini)
- [ ] Hallucinated method case → **REJECTED**
- [ ] Enable **Fast audit** if Pro audit feels slow (~60–80s)

---

## After VM reboot

```bash
cat /var/log/aegis-tunnel.url          # new URL
sudo systemctl restart cloudflared-quick
# Update API URL in Pages UI
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| CORS error in browser | `CORS_ORIGINS` must exactly match Pages URL (`https://…pages.dev`) |
| `502` / tunnel down | `systemctl status cloudflared-quick aegis-api` |
| UI can't reach API | Tunnel URL changed — paste new URL from `/var/log/aegis-tunnel.url` |
| Mixed content blocked | API must be `https://` (tunnel), not `http://VM_IP:8080` |
| Audit timeout in UI | Enable **Fast audit** or wait up to 120s |

---

## Later: custom domain (optional)

When you add a domain to Cloudflare (free DNS plan):

1. Create a **named tunnel** — see main [README.md](./README.md) Part 2.
2. Use stable hostname `api.yourdomain.com` instead of `trycloudflare.com`.
3. No need to change the tunnel URL after reboots.

---

## Paid plan — when you need it

| Plan | Why |
|------|-----|
| **Free** | Quick Tunnel + Pages — enough for hackathon |
| **Workers Paid ($5/mo)** | Only if you add a Pages Function proxy and need >30s request duration |
| **Pages** | Free tier is sufficient for static UI |

For Pro audit (60–80s), calling the tunnel URL **directly from the browser** (this guide) avoids Workers timeout limits.
