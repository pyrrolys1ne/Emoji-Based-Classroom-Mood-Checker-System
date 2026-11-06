from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.accounts import Administrator, no_store
from app.core.security import require_teacher_or_admin
from app.schemas.contracts import EmotionStatistics, Envelope, ExportFilters, MultidimensionalStatistics, StatisticsFilters
from app.services import statistics
from app.services.accounts import Principal

router = APIRouter(dependencies=[Depends(no_store)])
Viewer = Annotated[Principal, Depends(require_teacher_or_admin)]


@router.get("/emoji/statistics", tags=["统计"], response_model=Envelope[EmotionStatistics])
def basic(principal: Viewer, filters: Annotated[StatisticsFilters, Query()]):
    return Envelope(data=statistics.statistics(principal, filters))


@router.get("/admin/statistics", tags=["统计"], response_model=Envelope[MultidimensionalStatistics])
def multidimensional(principal: Viewer, filters: Annotated[StatisticsFilters, Query()]):
    return Envelope(data=statistics.statistics(principal, filters, multidimensional=True))


@router.get("/admin/emoji/export", tags=["导出"], response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}, "description": "UTF-8 CSV 文件"}})
def export_csv(principal: Administrator, filters: Annotated[ExportFilters, Query()]):
    content = statistics.export_csv(principal, filters)
    return Response(content, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="classroom-emotions.csv"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
