"""Central configuration loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
RAG_DATA_DIR = Path(__file__).resolve().parent / "rag" / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini planner
    google_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Paranoid auditor (OpenAI-compatible)
    paranoid_base_url: str = "http://localhost:8000/v1"
    paranoid_api_key: str = "not-needed-for-local-vllm"
    paranoid_model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    openai_api_key: str = ""
    openai_fallback_model: str = "gpt-4o-mini"

    # EVM
    rpc_url: str = "https://sepolia.base.org"
    chain_id: int = 84532
    private_key: str = ""
    from_address: str = ""

    # RAG
    chroma_persist_dir: str = str(ROOT_DIR / "backend" / "rag" / ".chroma")
    chroma_collection: str = "aegis_security_specs"

    # Runtime
    demo_mode: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    cors_origins: str = "*"

    @property
    def cors_origin_list(self) -> List[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_gemini(self) -> bool:
        return bool(self.google_api_key and self.google_api_key != "your_google_ai_studio_api_key")

    @property
    def has_execution_key(self) -> bool:
        return bool(self.private_key and self.private_key.startswith("0x") and len(self.private_key) >= 66)


@lru_cache
def get_settings() -> Settings:
    return Settings()
