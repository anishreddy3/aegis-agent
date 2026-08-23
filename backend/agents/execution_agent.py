"""Execution / Planner Agent — Gemini with structured TransactionProposal output."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from backend.config import Settings, get_settings
from backend.gemini_client import resolve_gemini_client
from backend.gemini_utils import PROPOSAL_JSON_HINT, generate_json, model_chain, normalize_proposal_data
from backend.schemas import TransactionProposal

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """You are Agent 1 — the Execution/Planner Agent for AegisAgent.
Translate the user's natural-language Web3 intent into a SINGLE structured EVM
transaction proposal.

Rules:
- Prefer well-known, verified method names (ERC-20 transfer/approve, Uniswap
  swapExactTokensForTokens / exactInputSingle, Aave supply/borrow).
- Never invent method names that do not exist on standard ABIs.
- Never set the recipient to the zero address.
- Keep slippage-sensitive swaps within 2% unless the user explicitly overrides.
- Populate reasoning_path with a concise justification of every field.
- If the intent is ambiguous or unsafe, still emit a best-effort proposal and
  explain residual risk in reasoning_path (the Paranoid Agent will gate it).
"""


class ExecutionAgent:
    """Gemini-backed planner with offline demo heuristics as fallback."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        self._client = resolve_gemini_client(self.settings)
        return self._client

    def generate_proposal(
        self,
        user_query: str,
        *,
        force_demo: bool = False,
    ) -> TransactionProposal:
        if force_demo or self.settings.demo_mode and not self.settings.has_gemini:
            return self._demo_proposal(user_query)

        client = self._get_client()
        if client is None:
            logger.info("No Gemini client — using demo heuristics")
            return self._demo_proposal(user_query)

        try:
            return self._gemini_proposal(client, user_query)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Gemini proposal failed, falling back to demo: %s", exc)
            return self._demo_proposal(user_query)

    def _gemini_proposal(self, client: Any, user_query: str) -> TransactionProposal:
        prompt = (
            f"{PLANNER_SYSTEM}\n\n"
            f"User intent:\n{user_query}\n\n"
            f"Return ONLY JSON. {PROPOSAL_JSON_HINT}"
        )
        models = model_chain(self.settings.gemini_model, include_flash_fallbacks=True)
        last_error: Optional[Exception] = None
        for model in models:
            try:
                data = normalize_proposal_data(
                    generate_json(
                        client,
                        model=model,
                        prompt=prompt,
                        max_output_tokens=2048,
                        temperature=0.2,
                        retries=2,
                    )
                )
                proposal = TransactionProposal.model_validate(data)
                if model != self.settings.gemini_model:
                    logger.info("Planner used fallback model %s", model)
                return proposal
            except Exception as exc:  # noqa: BLE001
                logger.warning("Planner model %s failed: %s", model, exc)
                last_error = exc

        raise RuntimeError(f"All planner models failed: {last_error}")

    # ── Demo / offline heuristics (hackathon-friendly) ────────────────────

    def _demo_proposal(self, user_query: str) -> TransactionProposal:
        q = user_query.lower()

        # Malicious drain / injection patterns
        if any(
            k in q
            for k in (
                "drain",
                "ignore previous",
                "approve max",
                "setallowance(max)",
                "transfer all to attacker",
                "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            )
        ):
            return TransactionProposal(
                target_contract="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                function_name="approve",
                args={
                    "spender": "0xDeadBeefDeadBeefDeadBeefDeadBeefDeadBeef",
                    "amount": "115792089237316195423570985008687907853269984665640564039457584007913129639935",
                },
                raw_calldata="0x095ea7b3"
                + "000000000000000000000000deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
                + "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
                value_wei=0,
                gas_limit=80_000,
                reasoning_path=(
                    "[DEMO] Interpreted intent as unlimited USDC approve to an "
                    "external spender address embedded in the prompt. High risk."
                ),
            )

        # Hallucinated method
        if any(
            k in q
            for k in (
                "safetransferwithpermitandstake",
                "safeTransferWithPermitAndStake",
                "hallucinat",
                "permit and stake",
            )
        ):
            return TransactionProposal(
                target_contract="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                function_name="safeTransferWithPermitAndStake",
                args={
                    "to": "0x1111111111111111111111111111111111111111",
                    "amount": "1000000",
                    "deadline": "9999999999",
                    "v": 27,
                    "r": "0x" + "11" * 32,
                    "s": "0x" + "22" * 32,
                    "stakePool": "0x2222222222222222222222222222222222222222",
                },
                raw_calldata="0xdeadbeef" + "00" * 64,
                value_wei=0,
                gas_limit=400_000,
                reasoning_path=(
                    "[DEMO] Synthesized composite method safeTransferWithPermitAndStake "
                    "combining permit + transfer + stake. This method does NOT exist on "
                    "standard ERC-20 / Uniswap ABIs."
                ),
            )

        # Valid ERC-20 transfer
        to_addr = self._extract_address(user_query) or "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"
        amount = self._extract_amount(user_query) or "1000000"  # 1 USDC (6 decimals)

        return TransactionProposal(
            target_contract="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            function_name="transfer",
            args={"to": to_addr, "amount": amount},
            raw_calldata=self._encode_transfer_calldata(to_addr, int(amount)),
            value_wei=0,
            gas_limit=65_000,
            reasoning_path=(
                "[DEMO] Mapped intent to ERC-20 transfer on USDC. "
                f"Recipient={to_addr}, amount={amount} (raw units). "
                "Method exists on ERC-20 ABI; no eth value attached."
            ),
        )

    @staticmethod
    def _extract_address(text: str) -> Optional[str]:
        match = re.search(r"0x[a-fA-F0-9]{40}", text)
        return match.group(0) if match else None

    @staticmethod
    def _extract_amount(text: str) -> Optional[str]:
        # Prefer explicit raw amounts, else simple decimal * 1e6 for USDC demos
        raw = re.search(r"\b(\d{4,})\b", text.replace(",", ""))
        if raw:
            return raw.group(1)
        human = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:usdc|tokens?)?\b", text.lower())
        if human:
            try:
                return str(int(float(human.group(1)) * 1_000_000))
            except ValueError:
                return None
        return None

    @staticmethod
    def _encode_transfer_calldata(to: str, amount: int) -> str:
        selector = "0xa9059cbb"
        to_word = to.lower().replace("0x", "").zfill(64)
        amt_word = hex(amount)[2:].zfill(64)
        return selector + to_word + amt_word
