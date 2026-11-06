import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.accounts import no_store
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import require_teacher_or_admin
from app.schemas.contracts import DashboardConnection, Envelope, RealtimeDashboard, RecordFilters, WsTicketResponse
from app.services import realtime
from app.services.accounts import Principal

router = APIRouter(dependencies=[Depends(no_store)])
socket_router = APIRouter()
Viewer = Annotated[Principal, Depends(require_teacher_or_admin)]


@router.post("/auth/ws-ticket", tags=["实时看板"], response_model=Envelope[WsTicketResponse])
def ticket(principal: Viewer):
    return Envelope(data=realtime.issue_ticket(principal))


@router.get("/admin/dashboard/realtime", tags=["实时看板"], response_model=Envelope[RealtimeDashboard])
def dashboard(principal: Viewer, filters: Annotated[RecordFilters, Query()]):
    return Envelope(data=realtime.dashboard(principal, filters))


@socket_router.websocket("/ws/dashboard")
async def dashboard_socket(websocket: WebSocket):
    origins = websocket.headers.getlist("origin")
    if len(origins) != 1 or origins[0] not in get_settings().cors_origins:
        await websocket.close(code=1008)
        return
    try:
        if set(websocket.query_params) - {"ticket", "sessionId"} or any(
            len(websocket.query_params.getlist(key)) != 1 for key in websocket.query_params
        ):
            raise ValueError
        query = DashboardConnection.model_validate(dict(websocket.query_params))
        principal = await run_in_threadpool(realtime.consume_ticket, query.ticket)
        await run_in_threadpool(realtime.snapshot, principal, query.session_id)
    except (ApiError, ValidationError, ValueError):
        await websocket.close(code=1008)
        return
    except Exception:
        await websocket.close(code=1011)
        return
    await websocket.accept()

    async def watch():
        while True:
            event = await run_in_threadpool(realtime.snapshot, principal, query.session_id)
            await asyncio.wait_for(websocket.send_json(event.model_dump(mode="json", by_alias=True)), timeout=5)
            await asyncio.sleep(get_settings().realtime_poll_seconds)

    async def receive():
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            # 通道仅通知刷新，不接收业务载荷。
            raise ApiError(403, "FORBIDDEN", "实时通道不接受客户端业务消息。")

    tasks = [asyncio.create_task(watch()), asyncio.create_task(receive())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except ApiError:
        await websocket.close(code=1008)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        await websocket.close(code=1011)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
