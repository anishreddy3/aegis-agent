"""Build WDK-compatible sign payloads after gatekeeper approval (Option A)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.config import Settings, get_settings
from backend.schemas import TransactionProposal, WdkSignRequest


def _normalize_calldata(raw: str) -> str:
    cleaned = (raw or "0x").strip()
    if not cleaned.startswith("0x"):
        cleaned = "0x" + cleaned
    return cleaned.lower()


def approval_token(proposal: TransactionProposal, *, chain_id: int) -> str:
    """Deterministic token WDK policy uses to allow exactly one approved tx."""
    canonical = {
        "chain_id": chain_id,
        "to": proposal.target_contract.lower(),
        "data": _normalize_calldata(proposal.raw_calldata),
        "value": str(int(proposal.value_wei)),
        "function_name": proposal.function_name,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return digest[:32]


def build_wdk_sign_request(
    proposal: TransactionProposal,
    *,
    settings: Settings | None = None,
    gatekeeper: str = "APPROVED",
) -> WdkSignRequest:
    """Map an approved TransactionProposal to a WDK EVM sendTransaction shape."""
    cfg = settings or get_settings()
    calldata = _normalize_calldata(proposal.raw_calldata)
    chain_id = int(cfg.chain_id)
    token = approval_token(proposal, chain_id=chain_id)

    return WdkSignRequest(
        wdk_ready=True,
        chain="evm",
        blockchain="ethereum",
        to=proposal.target_contract,
        data=calldata,
        value=str(int(proposal.value_wei)),
        gas=int(proposal.gas_limit),
        chain_id=chain_id,
        gatekeeper=gatekeeper,  # type: ignore[arg-type]
        function_name=proposal.function_name,
        approval_token=token,
        policy_hint={
            "operation": "sendTransaction",
            "match_fields": ["to", "data", "value", "chainId"],
            "docs": "https://docs.wdk.tether.io/sdk/core-module/api-reference/",
        },
    )


def tx_matches_approval(
    tx: dict[str, Any],
    proposal: TransactionProposal,
    *,
    chain_id: int,
) -> bool:
    """Check WDK tx params against an Aegis-approved proposal."""
    expected_token = approval_token(proposal, chain_id=chain_id)
    to = str(tx.get("to", "")).lower()
    data = _normalize_calldata(str(tx.get("data", "0x")))
    value = tx.get("value")
    if isinstance(value, int):
        value_str = str(value)
    else:
        value_str = str(value or "0")
    actual = {
        "chain_id": chain_id,
        "to": to,
        "data": data,
        "value": value_str,
        "function_name": proposal.function_name,
    }
    digest = hashlib.sha256(
        json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    return digest == expected_token
