# AegisAgent — Epistemically Paranoid Autonomous Agent for Web3 Tx Validation

Dual-agent pipeline that translates natural-language intents into EVM calldata, retrieves verified ABIs/invariants via RAG, adversarially audits the proposal, and only then simulates or broadcasts to a testnet.

```
User Intent
    │
    ▼
┌─────────────────────┐
│  Execution Agent    │  Gemini (structured TransactionProposal)
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Vector Store / RAG │  ChromaDB · ABIs + security invariants
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Paranoid Gatekeeper│  OpenAI-compatible vLLM / NeevCloud
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
- `POST /reingest` — reload ABI / invariant fixtures

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

With `DEMO_MODE=true` (default) the pipeline uses deterministic offline heuristics so judges can demo without API keys. Set real keys in `.env` and `DEMO_MODE=false` to hit Gemini + your vLLM endpoint.

## Configuration

| Variable | Purpose |
|----------|---------|
| `GOOGLE_API_KEY` / `GEMINI_MODEL` | Planner agent |
| `PARANOID_BASE_URL` / `PARANOID_MODEL` | OpenAI-compatible auditor (NeevCloud / vLLM) |
| `OPENAI_API_KEY` | Fallback if custom `base_url` is down |
| `RPC_URL` / `CHAIN_ID` / `PRIVATE_KEY` | Testnet broadcast (optional) |
| `DEMO_MODE` | Offline planner + auditor heuristics |

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
├── frontend/app.py      # Streamlit dual-agent debate UI
├── .env.example
└── requirements.txt
```

## Security note

This is a hackathon / research prototype. Never point `PRIVATE_KEY` at a mainnet wallet. The Paranoid Agent reduces — but does not eliminate — LLM hallucination and prompt-injection risk.
