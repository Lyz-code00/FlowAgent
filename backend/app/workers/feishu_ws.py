import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("flowagent.feishu_ws")
_MAX_IN_FLIGHT = 20


def forward_event(
    payload: dict[str, Any],
    callback_url: str,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    owns_client = client is None
    http_client = client or httpx.Client(timeout=90)
    try:
        response = http_client.post(callback_url, json=payload)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "forwarded Feishu event status=%s message_id=%s",
            result.get("status"),
            result.get("message_id"),
        )
        return result
    finally:
        if owns_client:
            http_client.close()


def main() -> None:
    settings = get_settings()
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError(
            "FLOWAGENT_FEISHU_APP_ID and FLOWAGENT_FEISHU_APP_SECRET are required"
        )

    # Imported lazily so the HTTP application and unit tests do not pay the
    # SDK import cost or inherit its module-level event loop.
    import lark_oapi as lark

    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="feishu-event")
    capacity = BoundedSemaphore(_MAX_IN_FLIGHT)

    def process(data: Any) -> None:
        try:
            payload = json.loads(lark.JSON.marshal(data))
            forward_event(payload, settings.feishu_internal_callback_url)
        except Exception:
            logger.exception("failed to process Feishu long-connection event")
        finally:
            capacity.release()

    def on_message(data: Any) -> None:
        if not capacity.acquire(blocking=False):
            logger.error("dropping Feishu event because the worker queue is full")
            return
        executor.submit(process, data)

    dispatcher = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )
    client = lark.ws.Client(
        settings.feishu_app_id,
        settings.feishu_app_secret,
        event_handler=dispatcher,
        # The SDK's INFO connection log contains a short-lived access key and
        # ticket in the WebSocket URL, so keep SDK output at ERROR in production.
        log_level=lark.LogLevel.ERROR,
    )
    logger.info("starting Feishu WebSocket long connection")
    try:
        client.start()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    main()
