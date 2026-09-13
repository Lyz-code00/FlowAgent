import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.channels.base import ChannelVerificationError, UnsupportedMessage

logger = logging.getLogger("flowagent.feishu")

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
        message_id = str(
            payload.get("event", {}).get("message", {}).get("message_id") or ""
        )
        if message_id:
            try:
                await request.app.state.feishu_adapter.send_message(
                    source_message_id=message_id,
                    content=(
                        "暂不支持该消息类型。目前可发送文本、图片、语音、Markdown、TXT "
                        "和文本型 PDF 文件。"
                    ),
                )
            except Exception:
                logger.exception("failed to reply unsupported-message prompt")
        return JSONResponse(
            {"ok": True, "status": "unsupported", "message_id": message_id}
        )
    return JSONResponse(
        {"ok": True, "status": result.status, "message_id": result.message_id}
    )
