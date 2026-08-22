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
from backend.execution.web3_executor import Web3Executor
from backend.rag.vector_store import VectorStore
from backend.schemas import PipelineRequest, PipelineResponse

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
        "AegisAgent API starting (demo_mode=%s, gemini=%s)",
        settings.demo_mode,
        settings.has_gemini,
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


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "gemini_configured": settings.has_gemini,
        "execution_key_configured": settings.has_execution_key,
        "chain_id": settings.chain_id,
        "rpc_url": settings.rpc_url,
    }


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
    logger.info("Pipeline start query=%r force_demo=%s", query[:120], force)

    try:
        proposal = execution_agent.generate_proposal(query, force_demo=force)

        rag_query = (
            f"{proposal.function_name} {proposal.target_contract} "
            f"{query} ABI invariant slippage approve transfer"
        )
        rag_context = vector_store.query_specs(rag_query, top_k=4)

        audit = paranoid_agent.audit(proposal, rag_context, force_demo=force)

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
        return PipelineResponse(
            user_query=query,
            proposal=proposal,
            rag_context=rag_context,
            audit=audit,
            execution=execution,
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
