import httpx

from app.workers.feishu_ws import forward_event


def test_forward_event_posts_payload() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(
            200,
            json={"ok": True, "status": "processed", "message_id": "om_1"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = forward_event(
            {"header": {"event_type": "im.message.receive_v1"}},
            "http://backend:8000/api/v1/channels/feishu/events",
            client=client,
        )

    assert captured["url"].endswith("/api/v1/channels/feishu/events")
    assert b"im.message.receive_v1" in captured["body"]
    assert result["status"] == "processed"
