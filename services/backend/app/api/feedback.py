from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query

from app.api.accounts import CurrentUser, no_store
from app.core.security import require_student
from app.schemas.contracts import EmojiRecord, EmojiSubmission, Envelope, IdempotencyKey, RecordFilters
from app.services import feedback
from app.services.accounts import Principal

router = APIRouter(dependencies=[Depends(no_store)])
Student = Annotated[Principal, Depends(require_student)]


@router.post("/emoji", tags=["情绪"], response_model=Envelope[EmojiRecord])
def submit(body: EmojiSubmission, principal: Student, idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")]):
    return Envelope(data=feedback.submit(principal, body, idempotency_key))


@router.get("/emoji/history", tags=["情绪"], response_model=Envelope[list[EmojiRecord]])
def history(principal: CurrentUser, filters: Annotated[RecordFilters, Query()]):
    return Envelope(data=feedback.history(principal, filters))
