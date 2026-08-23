#!/usr/bin/env node
/** Quick test: approved tx ALLOW, random tx DENY under Aegis policy rules. */
import { wouldAllowSend } from "./aegis-policy.mjs";

const approved = {
  to: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
  data: "0xa9059cbb000000000000000000000000742d35cc6634c0532925a3b844bc9e7595f0beb000000000000000000000000000000000000000000000000000000000000f4240",
  value: "0",
  approval_token: "demo",
};

const good = wouldAllowSend(
  { to: approved.to, data: approved.data, value: 0n },
  approved,
);
const bad = wouldAllowSend(
  { to: approved.to, data: "0xdeadbeef", value: 0n },
  approved,
);

console.log("Policy allow approved calldata:", good);
console.log("Policy deny tampered calldata:", !bad);
if (!good || bad) process.exit(1);
console.log("✓ aegis-policy logic OK");
