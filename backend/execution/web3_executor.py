"""web3.py executor — simulate first, broadcast only when funded & approved."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Optional

from backend.config import Settings, get_settings
from backend.schemas import ExecutionResult, TransactionProposal

logger = logging.getLogger(__name__)


class Web3Executor:
    """Safe testnet dispatcher with dry-run simulation and mock fallback."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._w3 = None

    def _get_web3(self):
        if self._w3 is not None:
            return self._w3
        try:
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(self.settings.rpc_url, request_kwargs={"timeout": 20}))
            if not w3.is_connected():
                logger.warning("RPC not reachable: %s", self.settings.rpc_url)
                return None
            self._w3 = w3
            return w3
        except Exception as exc:  # noqa: BLE001
            logger.warning("web3 init failed: %s", exc)
            return None

    def execute(self, proposal: TransactionProposal) -> ExecutionResult:
        """Simulate (eth_call / estimate_gas), then optionally broadcast."""
        w3 = self._get_web3()

        if w3 is None or not self.settings.has_execution_key:
            return self._mock_success(proposal, reason="no private key or RPC unavailable")

        try:
            return self._simulate_and_maybe_broadcast(w3, proposal)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Execution failed: %s", exc)
            return ExecutionResult(
                simulated=True,
                simulation_ok=False,
                broadcast=False,
                tx_hash=None,
                gas_used=None,
                error=str(exc),
                mode="simulate",
            )

    def _simulate_and_maybe_broadcast(self, w3, proposal: TransactionProposal) -> ExecutionResult:
        from_addr = self.settings.from_address
        if not from_addr and self.settings.private_key:
            acct = w3.eth.account.from_key(self.settings.private_key)
            from_addr = acct.address

        tx = {
            "to": w3.to_checksum_address(proposal.target_contract),
            "from": w3.to_checksum_address(from_addr),
            "data": proposal.raw_calldata if proposal.raw_calldata.startswith("0x") else "0x" + proposal.raw_calldata,
            "value": int(proposal.value_wei),
            "chainId": self.settings.chain_id,
        }

        # Dry-run: eth_call + estimate_gas
        try:
            w3.eth.call({"to": tx["to"], "from": tx["from"], "data": tx["data"], "value": tx["value"]})
            gas_est = w3.eth.estimate_gas(
                {"to": tx["to"], "from": tx["from"], "data": tx["data"], "value": tx["value"]}
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                simulated=True,
                simulation_ok=False,
                broadcast=False,
                tx_hash=None,
                gas_used=None,
                error=f"Simulation reverted: {exc}",
                mode="simulate",
            )

        if not self.settings.has_execution_key:
            return ExecutionResult(
                simulated=True,
                simulation_ok=True,
                broadcast=False,
                tx_hash=self._deterministic_mock_hash(proposal),
                gas_used=int(gas_est),
                error=None,
                mode="simulate",
            )

        # Live broadcast (testnet only — caller responsibility)
        nonce = w3.eth.get_transaction_count(tx["from"])
        tx.update(
            {
                "gas": min(int(proposal.gas_limit), int(gas_est) * 2),
                "nonce": nonce,
                "maxFeePerGas": w3.to_wei(2, "gwei"),
                "maxPriorityFeePerGas": w3.to_wei(1, "gwei"),
            }
        )
        signed = w3.eth.account.sign_transaction(tx, self.settings.private_key)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = w3.eth.send_raw_transaction(raw)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        return ExecutionResult(
            simulated=True,
            simulation_ok=True,
            broadcast=True,
            tx_hash=receipt.transactionHash.hex(),
            gas_used=int(receipt.gasUsed),
            error=None,
            mode="broadcast",
        )

    def _mock_success(self, proposal: TransactionProposal, reason: str) -> ExecutionResult:
        gas = proposal.gas_limit or 65_000
        return ExecutionResult(
            simulated=True,
            simulation_ok=True,
            broadcast=False,
            tx_hash=self._deterministic_mock_hash(proposal),
            gas_used=gas,
            error=f"Mock mode ({reason})",
            mode="mock",
        )

    @staticmethod
    def _deterministic_mock_hash(proposal: TransactionProposal) -> str:
        payload = (
            f"{proposal.target_contract}:{proposal.function_name}:"
            f"{proposal.raw_calldata}:{time.time_ns()}"
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return "0x" + digest
