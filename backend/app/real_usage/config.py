from decimal import Decimal
from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import SettingsConfigDict
from sqlalchemy.engine import make_url
from app.core.config import Settings


class RealUsageSettings(Settings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", hide_input_in_errors=True)
    rag_runtime_mode: Literal["infrastructure", "real"]
    database_url: SecretStr = Field(...)
    jwt_secret: SecretStr = Field(...)
    model_backend: str = "qwen"
    allow_paid_models: bool = True
    storage_dir: Path = Path("/data/uploads")
    vector_uri: str = "/data/milvus.db"
    audit_dir: Path = Path("/audit")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1, le=20 * 1024 * 1024)
    max_document_chunks: int = Field(default=32, ge=1, le=128)
    max_input_tokens: int = Field(default=4096, ge=512, le=32768)
    max_output_tokens: int = Field(default=256, ge=32, le=2048)
    model_timeout_seconds: int = Field(default=30, ge=1, le=120)
    model_requests_per_minute: int = Field(default=6, ge=1, le=60)
    max_calls_per_day: int = Field(default=60, ge=1, le=1000)
    max_calls_total: int = Field(default=3, ge=0, le=1000000)
    max_embedding_calls_total: int = Field(default=0, ge=0, le=1000000)
    max_qwen_calls_total: int = Field(default=0, ge=0, le=1000000)
    daily_budget_cny: Decimal = Field(default=Decimal("0.01"), gt=0, le=100)
    monthly_budget_cny: Decimal = Field(default=Decimal("0.01"), gt=0, le=3000)
    strict_clock_protection: bool = False  # Legacy contracts; R4 approval requires True.
    duplicate_window_seconds: int = Field(default=300, ge=30, le=3600)
    embedding_rate: Decimal = Decimal("0.5")
    qwen_input_rate: Decimal = Decimal("0.8")
    qwen_output_rate: Decimal = Decimal("2")
    historical_model_requests: int = 6

    @model_validator(mode="after")
    def real_scope(self):
        url = make_url(self.database_url.get_secret_value())
        if (url.drivername != "postgresql+psycopg" or url.host != "real-postgres"
                or url.database != "rag_personal_real" or url.username != "rag_real"):
            raise ValueError("R1_DATABASE_SCOPE_INVALID")
        if self.vector_backend != "milvus":
            raise ValueError("R1_MODE_INVALID")
        if self.rag_runtime_mode == "real":
            if self.model_backend != "qwen" or not self.allow_paid_models:
                raise ValueError("R1_MODE_INVALID")
        elif self.model_backend != "mock" or self.allow_paid_models or self.dashscope_api_key.get_secret_value():
            raise ValueError("R2_INFRASTRUCTURE_CONFIGURATION_CONFLICT")
        if (self.qwen_model != "qwen-plus" or self.embedding_model != "text-embedding-v4"
                or self.qwen_base_url != "https://dashscope.aliyuncs.com/compatible-mode/v1"
                or self.embedding_dimension != 1024):
            raise ValueError("R1_MODEL_OR_REGION_INVALID")
        if (self.storage_dir.as_posix() != "/data/uploads" or self.vector_uri != "/data/milvus.db"
                or self.audit_dir.as_posix() != "/audit"):
            raise ValueError("R1_STORAGE_SCOPE_INVALID")
        if len(self.jwt_secret.get_secret_value()) < 32 or self.historical_model_requests != 6:
            raise ValueError("R1_SECRET_OR_HISTORY_INVALID")
        if (self.embedding_rate, self.qwen_input_rate, self.qwen_output_rate) != (
                Decimal("0.5"), Decimal("0.8"), Decimal("2")):
            raise ValueError("R1_PRICING_REVIEW_REQUIRED")
        return self