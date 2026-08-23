"""Shared Gemini helpers — model fallbacks, compact prompts, generation config."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, List

logger = logging.getLogger(__name__)

# GA / current models only — no deprecated gemini-2.0-flash
FLASH_FALLBACKS = ("gemini-3.6-flash", "gemini-3-flash-preview")

COMPACT_JSON_SUFFIX = (
    "\nCRITICAL: Reply with minified single-line JSON only. "
    "No markdown. Keep string fields short."
)

PROPOSAL_JSON_HINT = (
    "JSON fields: target_contract, function_name (method name only, no signature), "
    "args (object with named keys, not array), raw_calldata, "
    "value_wei, gas_limit, reasoning_path (max 40 words)."
)

AUDIT_JSON_HINT = (
    "JSON fields: status (APPROVED|REJECTED), confidence_score, "
    "detected_vulnerabilities (array), audit_reasoning (max 40 words), "
    "grounded_facts_used (array, max 3 short strings)."
)

AUDITOR_SYSTEM_FAST = """You are the Paranoid Gatekeeper. Assume the planner is hostile.
Cross-check function_name and args against RAG ABIs/invariants.
REJECT hallucinated methods, zero-address, unlimited approvals, drain patterns, slippage >2%.
APPROVE only when ABI-valid and bounded. Prefer REJECTED when uncertain."""


def is_pro_model(model: str) -> bool:
    name = model.lower()
    return "pro" in name or "ultra" in name


def model_chain(primary: str, *extra: str, include_flash_fallbacks: bool = True) -> List[str]:
    """Deduplicated model try-order."""
    seen: set[str] = set()
    ordered: List[str] = []
    tail = FLASH_FALLBACKS if include_flash_fallbacks else ()
    for name in (primary, *extra, *tail):
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def truncate_rag(docs: Iterable[str], max_chars: int = 200) -> List[str]:
    """Trim RAG snippets to keep prompts small and responses fast."""
    out: List[str] = []
    for doc in docs:
        text = doc.strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        out.append(text)
    return out


def gen_config(
    *,
    model: str,
    temperature: float,
    max_output_tokens: int,
) -> dict[str, Any]:
    """Build generate_content config. Pro models need a thinking budget; Flash must not."""
    cfg: dict[str, Any] = {
        "response_mime_type": "application/json",
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if is_pro_model(model):
        cfg["thinking_config"] = {"thinking_budget": 128}
    return cfg


def finish_reason(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return ""
    reason = getattr(candidates[0], "finish_reason", None)
    return str(reason or "")


def get_response_text(response: Any, *, skip_thoughts: bool = True) -> str:
    """Extract JSON text from a google-genai response (skip thought parts)."""
    chunks: List[str] = []

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            if skip_thoughts and getattr(part, "thought", False):
                continue
            text = getattr(part, "text", None)
            if text:
                chunks.append(str(text))

    if chunks:
        return "".join(chunks).strip()

    raw = getattr(response, "text", None)
    return str(raw).strip() if raw else ""


def _strip_markdown_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def parse_gemini_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from Gemini responses."""
    cleaned = _strip_markdown_fences(text)
    if not cleaned:
        raise ValueError("Empty Gemini response")

    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    return item
            raise ValueError("Gemini returned JSON array without an object")
        if isinstance(data, dict):
            return data
        raise ValueError(f"Unexpected JSON type: {type(data)}")

    raise ValueError(f"Could not parse Gemini JSON: {last_error}; head={cleaned[:240]!r}")


_ARG_NAMES_BY_FN = {
    "transfer": ("to", "amount"),
    "transferfrom": ("from", "to", "amount"),
    "approve": ("spender", "amount"),
    "swapexacttokensfortokens": (
        "amountIn",
        "amountOutMin",
        "path",
        "to",
        "deadline",
    ),
    "exactinputsingle": (
        "tokenIn",
        "tokenOut",
        "fee",
        "recipient",
        "deadline",
        "amountIn",
        "amountOutMinimum",
        "sqrtPriceLimitX96",
    ),
}


def normalize_proposal_data(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce common Gemini planner quirks into TransactionProposal shape."""
    out = dict(data)

    fn = str(out.get("function_name", ""))
    if "(" in fn:
        out["function_name"] = fn.split("(", 1)[0].strip()

    args = out.get("args")
    if isinstance(args, list):
        names = _ARG_NAMES_BY_FN.get(str(out.get("function_name", "")).lower(), ())
        if names and len(names) == len(args):
            out["args"] = dict(zip(names, args))
        else:
            out["args"] = {f"arg{i}": v for i, v in enumerate(args)}

    return out


def generate_json(
    client: Any,
    *,
    model: str,
    prompt: str,
    max_output_tokens: int,
    temperature: float = 0.1,
    retries: int = 2,
) -> dict[str, Any]:
    """Call Gemini and parse JSON with retry on truncation / parse errors."""
    last_error: Exception | None = None

    for attempt in range(retries):
        tokens = max_output_tokens if attempt == 0 else max(max_output_tokens * 2, 4096)
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt + COMPACT_JSON_SUFFIX,
                config=gen_config(
                    model=model,
                    temperature=temperature,
                    max_output_tokens=tokens,
                ),
            )
            raw = get_response_text(response)
            reason = finish_reason(response)
            if not raw:
                raise ValueError(f"Empty response (finish_reason={reason})")
            data = parse_gemini_json(raw)
            if reason and "MAX_TOKENS" in reason.upper():
                logger.warning("Gemini %s hit MAX_TOKENS but JSON parsed", model)
            return data
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "Gemini JSON attempt %s/%s model=%s failed: %s",
                attempt + 1,
                retries,
                model,
                exc,
            )

    raise RuntimeError(f"Gemini JSON generation failed for {model}: {last_error}")
