from datetime import datetime
from typing import Generic, TypeVar, Literal
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    code: str = "OK"
    message: str = "成功"
    data: T


class ErrorResponse(BaseModel):
    code: str
    message: str
    data: None = None
    request_id: str


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class KBInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)


class KBOut(KBInput):
    model_config = ConfigDict(from_attributes=True)
    id: str
    owner_id: str
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    knowledge_base_id: str
    name: str
    file_type: str
    size: int
    status: str
    progress: int
    chunk_count: int
    error_code: str | None
    created_at: datetime


class Citation(BaseModel):
    source_id: int
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    source_name: str
    source_location: dict
    text: str
    score: float


class SearchInput(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=10)


class SessionInput(BaseModel):
    knowledge_base_id: str
    title: str = Field(default="新会话", min_length=1, max_length=120)


class SessionOut(SessionInput):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime


class MessageInput(SearchInput):
    pass


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation]
    created_at: datetime
