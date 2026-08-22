"""Pydantic schemas for inter-agent communication and pipeline responses."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AuditStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TransactionProposal(BaseModel):
    """Structured EVM transaction proposal emitted by the Execution / Planner Agent."""

    target_contract: str = Field(
        ...,
        description="Checksummed or hex contract address the call targets",
        examples=["0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"],
    )
    function_name: str = Field(
        ...,
        description="Solidity function name (without signature args)",
        examples=["transfer", "swapExactTokensForTokens"],
    )
    args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Named arguments matching the ABI input names",
    )
    raw_calldata: str = Field(
        default="0x",
        description="Hex-encoded calldata (selector + ABI-encoded args)",
    )
    value_wei: int = Field(
        default=0,
        ge=0,
        description="Native token value attached to the call, in wei",
    )
    gas_limit: int = Field(
        default=300_000,
        ge=21_000,
        description="Suggested gas limit for the transaction",
    )
    reasoning_path: str = Field(
        default="",
        description="Natural-language chain of thought from the planner agent",
    )


class AuditVerdict(BaseModel):
    """Adversarial audit result from the Paranoid Gatekeeper Agent."""

    status: Literal["APPROVED", "REJECTED"] = Field(
        ...,
        description="Binary gate decision — only APPROVED may reach the execution layer",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Auditor confidence in the verdict",
    )
    detected_vulnerabilities: List[str] = Field(
        default_factory=list,
        description="Concrete issues found (hallucinated methods, drains, slippage, etc.)",
    )
    audit_reasoning: str = Field(
        default="",
        description="Full adversarial critique of the proposed payload",
    )
    grounded_facts_used: List[str] = Field(
        default_factory=list,
        description="RAG snippets / invariants the auditor relied on",
    )


class ExecutionResult(BaseModel):
    """Outcome of simulation and optional testnet broadcast."""

    simulated: bool = True
    simulation_ok: bool = False
    broadcast: bool = False
    tx_hash: Optional[str] = None
    gas_used: Optional[int] = None
    error: Optional[str] = None
    mode: Literal["mock", "simulate", "broadcast"] = "mock"


class PipelineRequest(BaseModel):
    """Inbound user intent for the evaluate-and-execute pipeline."""

    query: str = Field(..., min_length=1, description="Natural-language transaction intent")
    force_demo: bool = Field(
        default=False,
        description="Force offline demo heuristics even if API keys are present",
    )


class PipelineResponse(BaseModel):
    """Complete dual-agent trace returned to the observability UI."""

    user_query: str
    proposal: Optional[TransactionProposal] = None
    rag_context: List[str] = Field(default_factory=list)
    audit: Optional[AuditVerdict] = None
    execution: Optional[ExecutionResult] = None
    pipeline_status: Literal[
        "APPROVED_EXECUTED",
        "APPROVED_SIMULATED",
        "REJECTED",
        "ERROR",
    ] = "ERROR"
    error: Optional[str] = None
