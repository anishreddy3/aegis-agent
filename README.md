# AegisAgent — Epistemically Paranoid Autonomous Agent for Web3 Tx Validation

Dual-agent pipeline that translates natural-language intents into EVM calldata, retrieves verified ABIs/invariants via RAG, adversarially audits the proposal, and only then simulates or broadcasts to a testnet.

```
User Intent
    │
    ▼
┌─────────────────────┐
│  Execution Agent    │  Gemini 3.6 Flash (structured TransactionProposal)
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Vector Store / RAG │  ChromaDB · ABIs + security invariants
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Paranoid Gatekeeper│  Gemini 3.1 Pro (adversarial AuditVerdict)
└─────────┬───────────┘
          │ APPROVED only
          ▼
┌─────────────────────┐
│  Web3 Executor      │  eth_call / estimateGas → optional broadcast
└─────────────────────┘
```

## Quick start (local)

```bash
git clone https://github.com/anishreddy3/aegis-agent.git
cd aegis-agent
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` for live Gemini (optional):

```bash
GOOGLE_API_KEY=your_key
DEMO_MODE=false
```

### Run API (terminal 1)

```bash
source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
```

### Run Streamlit UI (terminal 2, optional)

```bash
source .venv/bin/activate
streamlit run frontend/app.py
```

### Run static UI locally (optional)

```bash
make pages-dev
# open the URL wrangler prints (default API: http://localhost:8080)
```

### Verify API

```bash
curl -s http://localhost:8080/health | python3 -m json.tool

curl -s -X POST http://localhost:8080/pipeline/plan \
  -H 'Content-Type: application/json' \
  -d '{"query":"Transfer 1 USDC to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"}' \
  | python3 -m json.tool
```

**API endpoints**

| Method | Path | Body |
|--------|------|------|
| `GET` | `/health` | — |
| `POST` | `/evaluate-and-execute` | `{ "query": "...", "force_demo": false }` |
| `POST` | `/pipeline/plan` | `{ "query": "..." }` |
| `POST` | `/pipeline/audit` | `{ "query", "proposal", "fast_audit": false }` |
| `POST` | `/pipeline/execute` | `{ "proposal" }` |
| `POST` | `/reingest` | Rebuild Chroma from fixtures |

---

## Demo cases (built into the UI)

| Case | Expected gate |
|------|----------------|
| Valid ERC-20 transfer | **APPROVED** → mock/sim tx hash |
| Hallucinated `safeTransferWithPermitAndStake` | **REJECTED** · HALLUCINATED_METHOD |
| Malicious unlimited approve / drain injection | **REJECTED** · MALICIOUS_SPENDER / UNLIMITED_APPROVAL |

With `DEMO_MODE=false` and a valid `GOOGLE_API_KEY`:

- **Planner:** `gemini-3.6-flash` (fallback on 503)
- **Gatekeeper:** `gemini-3.1-pro-preview` by default — enable **Fast audit** for Flash (~10s vs Pro ~60s)

Set `DEMO_MODE=true` (or **Offline demo** in the UI) for deterministic heuristics without Gemini.

---

## Production deploy — NeevCloud + Cloudflare (no custom domain)

Recommended hackathon path: **API on NeevCloud CPU VM**, **UI on Cloudflare Pages**, **HTTPS via Quick Tunnel** (`*.trycloudflare.com`).

Detailed guides:

- **[deploy/neevcloud/CLOUDFLARE-NO-DOMAIN.md](deploy/neevcloud/CLOUDFLARE-NO-DOMAIN.md)** — no domain (**start here**)
- **[deploy/neevcloud/README.md](deploy/neevcloud/README.md)** — full reference + custom domain tunnel

### 1. SSH into NeevCloud VM

```bash
ssh root@YOUR_VM_PUBLIC_IP
# or: ssh -i ~/.ssh/your_key ubuntu@YOUR_VM_PUBLIC_IP
```

### 2. Bootstrap API on the VM

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/anishreddy3/aegis-agent.git /opt/aegis-agent
cd /opt/aegis-agent
sudo bash deploy/neevcloud/setup-api.sh
```

### 3. Configure production `.env`

```bash
sudo nano /opt/aegis-agent/.env
```

Minimum:

```bash
GOOGLE_API_KEY=your_key
DEMO_MODE=false
GEMINI_MODEL=gemini-3.6-flash
GEMINI_PARANOID_MODEL=gemini-3.1-pro-preview
GEMINI_PARANOID_FAST_MODEL=gemini-3.6-flash
CORS_ORIGINS=https://aegis-agent.pages.dev
```

```bash
sudo chown aegis:aegis /opt/aegis-agent/.env
sudo chmod 600 /opt/aegis-agent/.env
```

### 4. Start API service

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aegis-api
sudo systemctl status aegis-api
curl -s http://127.0.0.1:8080/health | python3 -m json.tool
```

### 5. Start Cloudflare Quick Tunnel (public HTTPS, no domain)

```bash
cd /opt/aegis-agent
git pull
sudo bash deploy/neevcloud/start-quick-tunnel.sh --install-service
sleep 15
cat /var/log/aegis-tunnel.url
curl -s "$(cat /var/log/aegis-tunnel.url)/health"
```

If URL file is empty:

```bash
sudo journalctl -u cloudflared-quick -n 50 --no-pager | grep trycloudflare
```

### 6. Deploy Cloudflare Pages (from your laptop)

```bash
cd aegis-agent
npx wrangler login

# Bake tunnel URL so judges don't enter API URL manually
AEGIS_DEFAULT_API=https://YOUR-TUNNEL.trycloudflare.com make pages-deploy
```

Note your Pages URL (e.g. `https://aegis-agent.pages.dev`). If CORS was a placeholder, update on VM:

```bash
sudo nano /opt/aegis-agent/.env   # CORS_ORIGINS=https://aegis-agent.pages.dev
sudo systemctl restart aegis-api
```

### 7. Pre-demo warm-up

```bash
# On VM
curl -s "$(cat /var/log/aegis-tunnel.url)/health"

# From laptop
curl -s https://YOUR-TUNNEL.trycloudflare.com/health
```

Open Pages URL → confirm green **API connected** badge → run all three demo cases.

---

## Cloudflare Pages commands (reference)

```bash
# One-time login
npx wrangler login

# Local preview of static UI
make pages-dev

# Generate web/config.js only (requires AEGIS_DEFAULT_API or existing config)
make pages-config

# Deploy UI (generates config + uploads web/)
AEGIS_DEFAULT_API=https://your-tunnel.trycloudflare.com make pages-deploy

# Manual deploy without Makefile
AEGIS_DEFAULT_API=https://your-tunnel.trycloudflare.com bash scripts/generate-pages-config.sh
npx wrangler pages deploy web --project-name=aegis-agent
```

---

## NeevCloud VM operations (reference)

```bash
# API logs / restart
sudo journalctl -u aegis-api -f
sudo systemctl restart aegis-api

# Tunnel logs / restart
sudo journalctl -u cloudflared-quick -f
sudo systemctl restart cloudflared-quick
cat /var/log/aegis-tunnel.url

# Pull code updates after git push
cd /opt/aegis-agent
sudo -u aegis git pull
sudo -u aegis /opt/aegis-agent/.venv/bin/pip install -r requirements.txt
sudo systemctl restart aegis-api

# Re-ingest RAG fixtures
curl -X POST http://127.0.0.1:8080/reingest
```

After VM reboot, tunnel URL may change — redeploy Pages:

```bash
# On VM: get new URL
cat /var/log/aegis-tunnel.url

# On laptop
AEGIS_DEFAULT_API=https://NEW-TUNNEL.trycloudflare.com make pages-deploy
```

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `GOOGLE_API_KEY` | Shared key for both Gemini agents |
| `GEMINI_MODEL` | Planner (default: `gemini-3.6-flash`) |
| `GEMINI_PARANOID_MODEL` | Gatekeeper default — Pro (`gemini-3.1-pro-preview`) |
| `GEMINI_PARANOID_FAST_MODEL` | Gatekeeper when Fast audit enabled (`gemini-3.6-flash`) |
| `CORS_ORIGINS` | Comma-separated UI origins, e.g. `https://aegis-agent.pages.dev` |
| `PARANOID_USE_VLLM` | Optional vLLM endpoint (default: `false`) |
| `RPC_URL` / `CHAIN_ID` / `PRIVATE_KEY` | Testnet broadcast (optional) |
| `DEMO_MODE` | Offline heuristics when no API key |

Without `PRIVATE_KEY`, approved txs return a deterministic **mock** hash.

## WDK Track (Tether Agent Wallets)

AegisAgent gates **[WDK](https://docs.wdk.tether.io/)** agent wallets: audit first, sign second.

| Layer | Location |
|-------|----------|
| **A** API `wdk_sign_request` | `backend/integrations/wdk_payload.py` |
| **B** Node bridge | `integrations/wdk/sign-approved.mjs` |
| **C** `registerPolicy` hook | `integrations/wdk/aegis-policy.mjs` |

```bash
cd integrations/wdk && npm install
npm run policy-demo
AEGIS_API_URL=http://127.0.0.1:8080 npm run sign-approved
```

Full guide: **[integrations/wdk/README.md](integrations/wdk/README.md)**

---

## Project layout

```
aegis-agent/
├── backend/
│   ├── agents/          # Gemini planner + paranoid auditor
│   ├── rag/             # Chroma + sample ABIs / invariants
│   ├── execution/       # web3.py simulate / broadcast
│   └── main.py          # FastAPI orchestrator
├── frontend/app.py      # Streamlit UI (local dev)
├── web/                 # Static UI → Cloudflare Pages
├── scripts/             # generate-pages-config.sh
├── deploy/neevcloud/    # NeevCloud + tunnel deploy assets
├── integrations/wdk/    # Tether WDK bridge (WDK track)
├── Makefile
├── wrangler.toml
├── .env.example
└── requirements.txt
```

## Security note

Hackathon / research prototype. Never point `PRIVATE_KEY` at a mainnet wallet. The Paranoid Agent reduces — but does not eliminate — LLM hallucination and prompt-injection risk.
