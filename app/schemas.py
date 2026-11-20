"""Request / response models."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.utils.validators import MAX_MESSAGE_LENGTH, extract_single_cta_link


class PostingRequest(BaseModel):
    message: str = Field(
        ...,
        description=(
            f"Message to publish. Max {MAX_MESSAGE_LENGTH} characters and exactly one "
            "http(s) CTA link."
        ),
        examples=[
            "Check out our latest business platform and grow your online visibility. "
            "https://example.com"
        ],
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be empty.")
        if len(value) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Message must not exceed {MAX_MESSAGE_LENGTH} characters (got {len(value)})."
            )
        extract_single_cta_link(value)  # raises a ValueError subclass when invalid
        return value

    @property
    def cta_link(self) -> str:
        return extract_single_cta_link(self.message)


class PlatformResult(BaseModel):
    platform: str
    status: Literal["success", "failed"]
    posted_url: Optional[str] = None
    public_access: bool = False
    date: Optional[str] = Field(None, description="Posting date, YYYY-MM-DD.")
    time: Optional[str] = Field(None, description="Posting time, HH:MM:SS.")
    error: Optional[str] = None


class PostingSummary(BaseModel):
    total: int
    succeeded: int
    failed: int
    timezone: str


class PostingResponse(BaseModel):
    success: bool = Field(..., description="True when at least one platform succeeded.")
    results: List[PlatformResult]
    summary: PostingSummary


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[List[Dict[str, Any]]] = None


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorDetail
