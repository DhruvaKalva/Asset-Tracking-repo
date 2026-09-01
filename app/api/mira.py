"""Mira -- the dashboard assistant endpoint.

Stateless like the rest of the API: the client owns the transcript and posts it
back each turn, so a chat survives a page reload and does not pin a user to one
replica.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import mira
from app.schemas import MiraReply, MiraRequest

router = APIRouter(prefix="/mira", tags=["mira"])


@router.get("/health")
def mira_health():
    """Lets the UI hide the button rather than offer a chat that cannot answer."""
    return mira.health()


@router.post("/chat", response_model=MiraReply)
def mira_chat(payload: MiraRequest, db: Session = Depends(get_db)):
    result = mira.chat(db, [m.model_dump() for m in payload.messages])
    return MiraReply(**result)
