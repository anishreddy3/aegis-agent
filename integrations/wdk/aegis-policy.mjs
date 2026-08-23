/**
 * Option C — WDK registerPolicy hook for AegisAgent gatekeeper approvals.
 * @see https://docs.wdk.tether.io/sdk/core-module/api-reference/
 */

/**
 * @param {import('@tetherto/wdk').default} wdk
 * @param {{
 *   to: string;
 *   data: string;
 *   value: string;
 *   approval_token: string;
 * }} approved
 */
export function registerAegisGatePolicy(wdk, approved) {
  const wantTo = String(approved.to).toLowerCase();
  const wantData = normalizeHex(approved.data);
  const wantValue = BigInt(approved.value || "0");
  const token = approved.approval_token;

  return wdk.registerPolicy({
    id: "aegis-gatekeeper",
    name: "AegisAgent Paranoid Gate",
    scope: "project",
    wallet: "ethereum",
    rules: [
      {
        name: "allow-aegis-approved",
        operation: "sendTransaction",
        action: "ALLOW",
        reason: `AegisAgent APPROVED (${token})`,
        conditions: [
          (context) => {
            if (process.env.AEGIS_DEBUG_POLICY) {
              console.log("  [policy context]", JSON.stringify(context, jsonReplacer));
            }
            return txMatches(context, wantTo, wantData, wantValue);
          },
        ],
      },
      {
        name: "deny-unapproved-send",
        operation: "sendTransaction",
        action: "DENY",
        reason: "Transaction not approved by AegisAgent gatekeeper",
        conditions: [
          (context) => !txMatches(context, wantTo, wantData, wantValue),
        ],
      },
    ],
  });
}

/** @param {unknown} context */
function txMatches(context, wantTo, wantData, wantValue) {
  const params = resolveParams(context);
  const { to, data, value } = extractTxFields(params);
  return to === wantTo && data === wantData && value === wantValue;
}

/** @param {unknown} context */
function resolveParams(context) {
  const ctx = /** @type {Record<string, unknown>} */ (context || {});
  if (ctx.params !== undefined && ctx.params !== null) return ctx.params;
  const args = ctx.args;
  if (Array.isArray(args) && args.length > 0) return args[0];
  return ctx;
}

/** @param {unknown} raw */
function extractTxFields(raw) {
  const p = /** @type {Record<string, unknown>} */ (raw || {});
  const nested = /** @type {Record<string, unknown>} */ (p.transaction || p.tx || p.request || {});
  const src = Object.keys(nested).length ? nested : p;

  const to = String(src.to || src.recipient || "").toLowerCase();

  let data = src.data ?? src.input ?? src.calldata ?? "0x";
  if (data instanceof Uint8Array) {
    data = `0x${Buffer.from(data).toString("hex")}`;
  } else if (typeof data === "string") {
    data = normalizeHex(data);
  } else {
    data = normalizeHex(String(data));
  }

  let valueRaw = src.value ?? src.amount ?? 0;
  let value;
  if (typeof valueRaw === "bigint") {
    value = valueRaw;
  } else if (typeof valueRaw === "number") {
    value = BigInt(valueRaw);
  } else {
    value = BigInt(String(valueRaw ?? "0"));
  }

  return { to, data, value };
}

function normalizeHex(hex) {
  let h = hex.trim().toLowerCase();
  if (!h.startsWith("0x")) h = `0x${h}`;
  return h;
}

function jsonReplacer(_key, val) {
  if (typeof val === "bigint") return val.toString();
  if (val instanceof Uint8Array) return `0x${Buffer.from(val).toString("hex")}`;
  return val;
}

/**
 * Standalone policy check without broadcasting (for policy-demo.mjs).
 * @param {unknown} params
 * @param {{ to: string; data: string; value: string }} approved
 */
export function wouldAllowSend(contextOrParams, approved) {
  return txMatches(
    contextOrParams,
    String(approved.to).toLowerCase(),
    normalizeHex(approved.data),
    BigInt(approved.value || "0"),
  );
}
