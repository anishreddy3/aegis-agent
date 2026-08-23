#!/usr/bin/env node
/**
 * Option B — Full flow: AegisAgent pipeline → WDK policy → simulate sign.
 *
 * Usage:
 *   AEGIS_API_URL=https://your-api npm run sign-approved
 *   AEGIS_API_URL=http://127.0.0.1:8080 npm run sign-approved -- "Transfer 1 USDC to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"
 *
 * Requires WDK_TEST_SEED_PHRASE (12/24 words) or generates an ephemeral seed (dry-run only).
 */

import WDK from "@tetherto/wdk";
import WalletManagerEvm from "@tetherto/wdk-wallet-evm";
import { registerAegisGatePolicy } from "./aegis-policy.mjs";

const API = (process.env.AEGIS_API_URL || "http://127.0.0.1:8080").replace(/\/$/, "");
const RPC = process.env.WDK_EVM_RPC || "https://sepolia.base.org";
const QUERY =
  process.argv.slice(2).join(" ") ||
  "Transfer 1 USDC to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0";

async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${path} ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}

async function runAegisPipeline(query) {
  console.log("▶ AegisAgent pipeline…");
  const plan = await post("/pipeline/plan", { query, force_demo: false });
  const proposal = plan.proposal;
  console.log(`  Planner: ${proposal.function_name} → ${proposal.target_contract}`);

  const auditResp = await post("/pipeline/audit", {
    query,
    proposal,
    force_demo: false,
    fast_audit: true,
  });
  const audit = auditResp.audit;
  console.log(`  Gatekeeper: ${audit.status} (confidence ${audit.confidence_score})`);

  if (audit.status !== "APPROVED") {
    console.log("\n✗ REJECTED — WDK sign blocked by policy design.");
    console.log("  Vulnerabilities:", audit.detected_vulnerabilities?.join(", ") || "—");
    process.exit(0);
  }

  const execResp = await post("/pipeline/execute", { proposal });
  const wdkReq = execResp.wdk_sign_request;
  if (!wdkReq?.wdk_ready) {
    throw new Error("Execute succeeded but wdk_sign_request missing");
  }
  console.log("  WDK payload ready (Option A):", JSON.stringify(wdkReq, null, 2));
  return wdkReq;
}

async function runWdkSimulation(wdkReq) {
  console.log("\n▶ WDK @tetherto/wdk (Option B + C)…");
  const seed =
    process.env.WDK_TEST_SEED_PHRASE?.trim() || WDK.getRandomSeedPhrase(12);
  if (!process.env.WDK_TEST_SEED_PHRASE) {
    console.log("  (ephemeral seed — fund not required for simulate)");
  }

  let wdk = new WDK(seed).registerWallet("ethereum", WalletManagerEvm, {
    provider: RPC,
  });
  wdk = registerAegisGatePolicy(wdk, wdkReq);

  const account = await wdk.getAccount("ethereum", 0);
  const address = await account.getAddress();
  console.log(`  WDK account[0]: ${address}`);

  const tx = {
    to: wdkReq.to,
    data: wdkReq.data,
    value: BigInt(wdkReq.value || "0"),
  };

  const simAccount = /** @type {{ simulate?: { sendTransaction: (t: unknown) => Promise<{ decision?: string; reason?: string }> } }} */ (
    account
  );
  if (simAccount.simulate?.sendTransaction) {
    const simulation = await simAccount.simulate.sendTransaction(tx);
    console.log(`  simulate.sendTransaction → ${simulation.decision || "OK"}`);
    if (simulation.reason) console.log(`  reason: ${simulation.reason}`);
    if (simulation.decision === "DENY") {
      console.log("  (Policy enforced — if unexpected, check calldata match in aegis-policy.mjs)");
    }
  } else {
    console.log("  simulate API not exposed — attempting sendTransaction dry path");
    try {
      await account.sendTransaction(tx);
      console.log("  sendTransaction succeeded");
    } catch (err) {
      console.log(`  sendTransaction blocked/ failed (expected on unfunded testnet): ${err.message}`);
    }
  }

  wdk.dispose?.(["ethereum"]);
  console.log("\n✓ WDK integration demo complete.");
}

async function main() {
  console.log(`Aegis API: ${API}`);
  const wdkReq = await runAegisPipeline(QUERY);
  await runWdkSimulation(wdkReq);
}

main().catch((err) => {
  console.error("Fatal:", err.message || err);
  process.exit(1);
});
