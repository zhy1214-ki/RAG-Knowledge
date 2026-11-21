from pathlib import Path
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: SecretStr = SecretStr("sqlite:///./data/app.db")
    jwt_secret: SecretStr = SecretStr("local-demo-change-this-secret-before-production")
    token_hours: int = 12
    storage_dir: Path = ROOT / "data" / "uploads"
    vector_uri: str = str(ROOT / "data" / "milvus.db")
    vector_backend: str = "milvus"
    model_backend: str = "mock"
    allow_paid_models: bool = False
    dashscope_api_key: SecretStr = SecretStr("")
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v4"
    embedding_dimension: int = 1024
    max_upload_bytes: int = 20 * 1024 * 1024
    chunk_size: int = 384
    chunk_overlap: int = 48
    min_score: float = 0.2
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @model_validator(mode="after")
    def validate_modes(self):
        if self.model_backend not in {"mock", "qwen"} or self.vector_backend not in {"memory", "milvus"}:
            raise ValueError("Unsupported backend")
        if self.embedding_dimension != 1024:
            raise ValueError("V1 index dimension must be 1024")
        if self.model_backend == "qwen" and (not self.allow_paid_models or not self.dashscope_api_key.get_secret_value()):
            raise ValueError("Qwen requires explicit paid-model opt-in and API key")
        return self
