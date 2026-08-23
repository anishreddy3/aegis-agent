"""FastAPI orchestrator — dual-agent evaluate-and-execute pipeline."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.execution_agent import ExecutionAgent
from backend.agents.paranoid_agent import ParanoidAgent
from backend.config import get_settings
from backend.integrations.wdk_payload import build_wdk_sign_request
from backend.execution.web3_executor import Web3Executor
from backend.rag.vector_store import VectorStore
from backend.schemas import (
    PipelineRequest,
    PipelineResponse,
    StageAuditRequest,
    StageAuditResponse,
    StageExecuteRequest,
    StageExecuteResponse,
    StagePlanRequest,
    StagePlanResponse,
    TransactionProposal,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aegis.api")

settings = get_settings()
execution_agent = ExecutionAgent(settings)
paranoid_agent = ParanoidAgent(settings)
vector_store = VectorStore(settings)
web3_executor = Web3Executor(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info(
        "AegisAgent API starting (demo_mode=%s, gemini=%s, planner=%s, auditor=%s)",
        settings.demo_mode,
        settings.has_gemini,
        settings.gemini_model,
        settings.gemini_paranoid_model,
    )
    # Ensure fixtures are present
    if vector_store._collection is not None and vector_store._collection.count() == 0:
        vector_store.ingest_fixtures()
    yield
    logger.info("AegisAgent API shutting down")


app = FastAPI(
    title="AegisAgent",
    description=(
        "Epistemically Paranoid Autonomous Agent framework for "
        "Web3 transaction validation — dual-agent gate before broadcast."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_fast_audit(*, fast_audit: bool = False, deep_audit: bool = False) -> bool:
    """Legacy deep_audit=True implied Pro; fast_audit=True selects Flash."""
    if fast_audit:
        return True
    if deep_audit:
        return False
    return False


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "gemini_configured": settings.has_gemini,
        "planner_model": settings.gemini_model,
        "paranoid_model": settings.gemini_paranoid_model,
        "paranoid_fast_model": settings.gemini_paranoid_fast_model,
        "paranoid_use_vllm": settings.paranoid_use_vllm,
        "execution_key_configured": settings.has_execution_key,
        "chain_id": settings.chain_id,
        "rpc_url": settings.rpc_url,
        "wdk_integration": True,
    }


def _rag_query(proposal: TransactionProposal, user_query: str) -> str:
    return (
        f"{proposal.function_name} {proposal.target_contract} "
        f"{user_query} ABI invariant slippage approve transfer"
    )


def _run_plan(query: str, *, force_demo: bool) -> TransactionProposal:
    return execution_agent.generate_proposal(query, force_demo=force_demo)


def _run_audit(
    query: str,
    proposal: TransactionProposal,
    *,
    force_demo: bool,
    fast_audit: bool,
):
    rag_context = vector_store.query_specs(_rag_query(proposal, query), top_k=2)
    audit = paranoid_agent.audit(
        proposal,
        rag_context,
        force_demo=force_demo,
        fast_audit=fast_audit,
    )
    return rag_context, audit


@app.post("/pipeline/plan", response_model=StagePlanResponse)
def pipeline_plan(body: StagePlanRequest) -> StagePlanResponse:
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    logger.info("Pipeline stage=plan query=%r", query[:120])
    proposal = _run_plan(query, force_demo=body.force_demo)
    return StagePlanResponse(proposal=proposal)


@app.post("/pipeline/audit", response_model=StageAuditResponse)
def pipeline_audit(body: StageAuditRequest) -> StageAuditResponse:
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    logger.info("Pipeline stage=audit function=%s", body.proposal.function_name)
    rag_context, audit = _run_audit(
        query,
        body.proposal,
        force_demo=body.force_demo,
        fast_audit=_resolve_fast_audit(
            fast_audit=body.fast_audit,
            deep_audit=body.deep_audit,
        ),
    )
    return StageAuditResponse(audit=audit, rag_context=rag_context)


@app.post("/pipeline/execute", response_model=StageExecuteResponse)
def pipeline_execute(body: StageExecuteRequest) -> StageExecuteResponse:
    logger.info("Pipeline stage=execute function=%s", body.proposal.function_name)
    execution = web3_executor.execute(body.proposal)
    wdk = build_wdk_sign_request(body.proposal) if execution.simulation_ok else None
    return StageExecuteResponse(execution=execution, wdk_sign_request=wdk)


@app.post("/evaluate-and-execute", response_model=PipelineResponse)
def evaluate_and_execute(body: PipelineRequest) -> PipelineResponse:
    """
    Full pipeline:
      1. ExecutionAgent.generate_proposal
      2. VectorStore.query_specs
      3. ParanoidAgent.audit
      4. Web3Executor.execute  (only if APPROVED)
    """
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")

    force = body.force_demo
    fast = _resolve_fast_audit(fast_audit=body.fast_audit, deep_audit=body.deep_audit)
    logger.info("Pipeline start query=%r force_demo=%s fast_audit=%s", query[:120], force, fast)

    try:
        proposal = _run_plan(query, force_demo=force)
        rag_context, audit = _run_audit(
            query,
            proposal,
            force_demo=force,
            fast_audit=fast,
        )

        if audit.status != "APPROVED":
            return PipelineResponse(
                user_query=query,
                proposal=proposal,
                rag_context=rag_context,
                audit=audit,
                execution=None,
                pipeline_status="REJECTED",
            )

        execution = web3_executor.execute(proposal)
        status = (
            "APPROVED_EXECUTED"
            if execution.broadcast
            else "APPROVED_SIMULATED"
        )
        wdk = build_wdk_sign_request(proposal) if execution.simulation_ok else None
        return PipelineResponse(
            user_query=query,
            proposal=proposal,
            rag_context=rag_context,
            audit=audit,
            execution=execution,
            wdk_sign_request=wdk,
            pipeline_status=status,
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline error")
        return PipelineResponse(
            user_query=query,
            pipeline_status="ERROR",
            error=str(exc),
        )


@app.post("/reingest")
def reingest() -> dict[str, Any]:
    """Reload ABI / invariant fixtures into Chroma (ops helper)."""
    count = vector_store.ingest_fixtures()
    return {"ingested": count}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
