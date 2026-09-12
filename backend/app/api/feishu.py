import json

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.channels.base import ChannelVerificationError, UnsupportedMessage

router = APIRouter(prefix="/api/v1/channels/feishu", tags=["feishu"])


@router.post("/events")
async def receive_event(request: Request) -> JSONResponse:
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid JSON payload"
        ) from exc

    adapter = request.app.state.feishu_adapter
    try:
        adapter.verify_event(body=body, headers=request.headers, payload=payload)
    except ChannelVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        if not challenge:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="missing URL verification challenge",
            )
        return JSONResponse({"challenge": challenge})

    try:
        result = await request.app.state.message_gateway.process(payload)
    except UnsupportedMessage:
        return JSONResponse({"ok": True, "status": "ignored"})
    return JSONResponse(
        {"ok": True, "status": result.status, "message_id": result.message_id}
    )
