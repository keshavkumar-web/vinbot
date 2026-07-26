"""Pydantic request/response models for the API."""

from pydantic import BaseModel, Field


class SessionResponse(BaseModel):
    session_id: str


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Session id obtained from /api/session")
    message: str = Field(..., min_length=1, description="The user's message")


class ResetRequest(BaseModel):
    session_id: str


class SimpleResponse(BaseModel):
    ok: bool
