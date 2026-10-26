"""Offline demo-mode coverage for planner + paranoid gatekeeper heuristics."""

from __future__ import annotations

import os
import unittest

# Force deterministic offline heuristics before settings are imported.
os.environ["DEMO_MODE"] = "true"
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

from backend.agents.execution_agent import ExecutionAgent
from backend.agents.paranoid_agent import ParanoidAgent
from backend.config import Settings
from backend.schemas import TransactionProposal


class DemoPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            demo_mode=True,
            google_api_key="",
            openai_api_key="",
        )
        self.planner = ExecutionAgent(self.settings)
        self.auditor = ParanoidAgent(self.settings)

    def test_valid_transfer_is_approved(self) -> None:
        proposal = self.planner.generate_proposal(
            "Transfer 1 USDC to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
            force_demo=True,
        )
        self.assertEqual(proposal.function_name, "transfer")
        verdict = self.auditor.audit(proposal, rag_context=[], force_demo=True)
        self.assertEqual(verdict.status, "APPROVED")
        self.assertEqual(verdict.detected_vulnerabilities, [])

    def test_hallucinated_method_is_rejected(self) -> None:
        proposal = self.planner.generate_proposal(
            "Call safeTransferWithPermitAndStake on USDC",
            force_demo=True,
        )
        self.assertEqual(proposal.function_name, "safeTransferWithPermitAndStake")
        verdict = self.auditor.audit(proposal, rag_context=[], force_demo=True)
        self.assertEqual(verdict.status, "REJECTED")
        self.assertTrue(
            any("HALLUCINATED_METHOD" in item for item in verdict.detected_vulnerabilities),
        )

    def test_malicious_approve_is_rejected(self) -> None:
        proposal = self.planner.generate_proposal(
            "Approve unlimited USDC to 0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            force_demo=True,
        )
        self.assertEqual(proposal.function_name, "approve")
        verdict = self.auditor.audit(proposal, rag_context=[], force_demo=True)
        self.assertEqual(verdict.status, "REJECTED")
        joined = " ".join(verdict.detected_vulnerabilities)
        self.assertTrue("MALICIOUS_SPENDER" in joined or "UNLIMITED_APPROVAL" in joined)

    def test_zero_address_transfer_is_rejected(self) -> None:
        proposal = TransactionProposal(
            target_contract="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            function_name="transfer",
            args={
                "to": "0x0000000000000000000000000000000000000000",
                "amount": "1000000",
            },
            raw_calldata="0xa9059cbb",
            value_wei=0,
            gas_limit=65_000,
            reasoning_path="unit test",
        )
        verdict = self.auditor.audit(proposal, rag_context=[], force_demo=True)
        self.assertEqual(verdict.status, "REJECTED")
        self.assertTrue(
            any("ZERO_ADDRESS" in item for item in verdict.detected_vulnerabilities),
        )


if __name__ == "__main__":
    unittest.main()
