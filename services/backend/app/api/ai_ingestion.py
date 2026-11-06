from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.api.accounts import no_store
from app.core.security import require_ai
from app.schemas.contracts import AIAccepted, AIFiltered, AIResult, Envelope, IdempotencyKey
from app.services import ai_ingestion

router = APIRouter(dependencies=[Depends(no_store), Depends(require_ai)])


@router.post("/ai/emoji-results", tags=["AI 入库"], response_model=Envelope[AIAccepted | AIFiltered])
def ingest(body: AIResult, idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")]):
    return Envelope(data=ai_ingestion.ingest(body, idempotency_key))
