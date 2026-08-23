# AegisAgent × Tether WDK Integration

**Aleph Hackathon — WDK Track**

AegisAgent is a **mandatory security gate** before [WDK](https://docs.wdk.tether.io/) agent wallets sign transactions. Natural language → structured proposal → RAG + adversarial audit → **only then** WDK `sendTransaction`.

## Three integration layers

| Option | Location | What it does |
|--------|----------|--------------|
| **A** | `backend/integrations/wdk_payload.py` + API `/pipeline/execute` | Returns `wdk_sign_request` JSON after APPROVED |
| **B** | `sign-approved.mjs` | Node bridge: Aegis pipeline → `@tetherto/wdk` simulate/sign |
| **C** | `aegis-policy.mjs` | `registerPolicy` DENY/ALLOW rules — only Aegis-approved calldata passes |

## Quick start

```bash
# Terminal 1 — Aegis API
uvicorn backend.main:app --host 0.0.0.0 --port 8080

# Terminal 2 — WDK bridge
cd integrations/wdk
npm install
npm run policy-demo
AEGIS_API_URL=http://127.0.0.1:8080 npm run sign-approved
```

### Environment

| Variable | Purpose |
|----------|---------|
| `AEGIS_API_URL` | Running AegisAgent FastAPI base URL |
| `WDK_EVM_RPC` | EVM RPC for WDK (default: Base Sepolia) |
| `WDK_TEST_SEED_PHRASE` | Optional 12/24-word seed; ephemeral if unset |

## Option A — API payload

After gatekeeper **APPROVED**, execute returns:

```json
{
  "wdk_sign_request": {
    "wdk_ready": true,
    "chain": "evm",
    "blockchain": "ethereum",
    "to": "0xA0b8…",
    "data": "0xa9059cbb…",
    "value": "0",
    "gas": 65000,
    "chain_id": 84532,
    "gatekeeper": "APPROVED",
    "approval_token": "abc123…",
    "policy_hint": { "operation": "sendTransaction" }
  }
}
```

Visible in the Cloudflare Pages UI under **Dispatch → WDK sign request**.

## Option C — Policy hook

```javascript
import { registerAegisGatePolicy } from "./aegis-policy.mjs";

wdk = registerAegisGatePolicy(wdk, wdkSignRequestFromAegis);
const account = await wdk.getAccount("ethereum", 0);
await account.simulate.sendTransaction({ to, data, value });
```

Unapproved or tampered calldata → `PolicyViolationError` ([WDK docs](https://docs.wdk.tether.io/sdk/core-module/api-reference/)).

## Architecture

```
User intent
    → Gemini Planner (proposal)
    → Chroma RAG + Gemini Pro Gatekeeper
    → APPROVED?
         yes → wdk_sign_request (Option A)
              → WDK registerPolicy (Option C)
              → sendTransaction / simulate (Option B)
         no  → WDK never signs
```

## Demo video script (WDK track)

1. Problem: *WDK agent wallets can sign anything the planner hallucinates*
2. Show APPROVED transfer → WDK payload + simulate
3. Show REJECTED hallucinated method → no WDK payload
4. Mention `@tetherto/wdk` policy integration (this folder)

## References

- [WDK Get Started](https://docs.wdk.tether.io/sdk/get-started/)
- [WDK registerPolicy](https://docs.wdk.tether.io/sdk/core-module/api-reference/)
- [AegisAgent README](../../README.md)
