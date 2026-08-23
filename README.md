# AegisAgent — Epistemically Paranoid Autonomous Agent for Web3 Tx Validation

Dual-agent pipeline that translates natural-language intents into EVM calldata, retrieves verified ABIs/invariants via RAG, adversarially audits the proposal, and only then simulates or broadcasts to a testnet.

```
User Intent
    │
    ▼
┌─────────────────────┐
│  Execution Agent    │  Gemini 3.7 Flash (structured TransactionProposal)
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

## Quick start

```bash
cd aegis-agent
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # works out of the box with DEMO_MODE=true
```

### API

```bash
# from repo root so `backend` is importable
uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
```

- `GET /health`
- `POST /evaluate-and-execute` — body `{ "query": "...", "force_demo": true }`
- `POST /pipeline/plan` · `/pipeline/audit` · `/pipeline/execute` — staged pipeline for live UI progress

### Observability UI

```bash
streamlit run frontend/app.py
```

Open the Streamlit URL, pick a pre-loaded demo, and hit **Evaluate & Execute**.

## Demo cases (built into the UI)

| Case | Expected gate |
|------|----------------|
| Valid ERC-20 transfer | **APPROVED** → mock/sim tx hash |
| Hallucinated `safeTransferWithPermitAndStake` | **REJECTED** · HALLUCINATED_METHOD |
| Malicious unlimited approve / drain injection | **REJECTED** · MALICIOUS_SPENDER / UNLIMITED_APPROVAL |

With `DEMO_MODE=false` and a valid `GOOGLE_API_KEY`, both agents run live on Gemini:
- **Planner:** `gemini-3.6-flash` (fallback chain on 503)
- **Paranoid Gatekeeper:** `gemini-3.1-pro-preview` by default — check **Fast audit** for Flash

Set `DEMO_MODE=true` (or check "Force offline demo heuristics") for deterministic offline mode.

## Cloudflare Pages (static UI)

The **`web/`** directory is a static dashboard deployable to Cloudflare Pages.  
**The Python API must run elsewhere** (NeevCloud, Railway, Fly.io, Render, or your laptop + tunnel).

```bash
# one-time
npx wrangler login

# deploy UI
make pages-deploy
# or: npx wrangler pages deploy web --project-name=aegis-agent
```

After deploy, open your Pages URL — the API URL is preconfigured if you used `AEGIS_DEFAULT_API` (see [deploy/neevcloud/CLOUDFLARE-NO-DOMAIN.md](deploy/neevcloud/CLOUDFLARE-NO-DOMAIN.md)).

```bash
AEGIS_DEFAULT_API=https://your-tunnel.trycloudflare.com make pages-deploy
```

Add your Pages origin to `CORS_ORIGINS` in the API `.env`.

Local preview: `make pages-dev`

## Production deploy (NeevCloud + Cloudflare)

Full guide: **[deploy/neevcloud/README.md](deploy/neevcloud/README.md)**

Quick path on a fresh **Ubuntu 24.04 CPU VM** (NanoBoost 2 vCPU / 4 GB recommended):

```bash
sudo git clone https://github.com/anishreddy3/aegis-agent.git /opt/aegis-agent
cd /opt/aegis-agent
sudo bash deploy/neevcloud/setup-api.sh
sudo nano /opt/aegis-agent/.env          # GOOGLE_API_KEY, CORS_ORIGINS
sudo systemctl enable --now aegis-api
```

Then expose HTTPS with **Cloudflare Tunnel** — see:

- **No domain:** [deploy/neevcloud/CLOUDFLARE-NO-DOMAIN.md](deploy/neevcloud/CLOUDFLARE-NO-DOMAIN.md) (Quick Tunnel + Pages — **start here**)
- **Custom domain:** [deploy/neevcloud/README.md](deploy/neevcloud/README.md) Part 2 (named tunnel)

Included in `deploy/neevcloud/`:

| File | Purpose |
|------|---------|
| `README.md` | Step-by-step NeevCloud + Pages + tunnel guide |
| `setup-api.sh` | VM bootstrap (Python venv, systemd) |
| `aegis-api.service` | systemd unit for uvicorn |
| `cloudflared-config.yml.example` | Tunnel ingress to `:8080` |
| `cloudflared.service` | systemd unit for cloudflared |
| `env.production.example` | Production `.env` template |
| `Caddyfile.example` | Optional reverse proxy (no tunnel) |

## Configuration

| Variable | Purpose |
|----------|---------|
| `GOOGLE_API_KEY` | Shared key for both Gemini agents |
| `GEMINI_MODEL` | Planner agent (default: `gemini-3.6-flash`) |
| `GEMINI_PARANOID_MODEL` | Gatekeeper default — Pro (default: `gemini-3.1-pro-preview`) |
| `GEMINI_PARANOID_FAST_MODEL` | Gatekeeper when Fast audit enabled (`gemini-3.7-flash`) |
| `PARANOID_USE_VLLM` | Enable optional vLLM/NeevCloud endpoint (default: `false`) |
| `OPENAI_API_KEY` | Optional fallback if vLLM is enabled |
| `RPC_URL` / `CHAIN_ID` / `PRIVATE_KEY` | Testnet broadcast (optional) |
| `DEMO_MODE` | Offline heuristics when no API key |

Without `PRIVATE_KEY`, approved txs return a deterministic **mock** hash after local simulation logic (or skip RPC if unreachable).

## Project layout

```
aegis-agent/
├── backend/
│   ├── config.py
│   ├── schemas.py
│   ├── agents/          # Gemini planner + paranoid auditor
│   ├── rag/             # Chroma + sample ABIs / invariants
│   ├── execution/       # web3.py simulate / broadcast
│   └── main.py          # FastAPI orchestrator
├── frontend/app.py      # Streamlit UI (local dev)
├── web/                 # Static UI → Cloudflare Pages
├── deploy/neevcloud/    # NeevCloud CPU VM + Cloudflare Tunnel
├── wrangler.toml
├── .env.example
└── requirements.txt
```

## Security note

This is a hackathon / research prototype. Never point `PRIVATE_KEY` at a mainnet wallet. The Paranoid Agent reduces — but does not eliminate — LLM hallucination and prompt-injection risk.
