from pathlib import Path

from app.services.transcription_service import LocalWhisperTranscriptionService


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeWhisperModel:
    def transcribe(self, path: str, **kwargs):
        assert Path(path).read_bytes() == b"fake-audio"
        assert kwargs["vad_filter"] is True
        return [FakeSegment(" 你好"), FakeSegment("，FlowAgent。")], {}


async def test_local_transcription_keeps_audio_on_local_tempfile() -> None:
    service = LocalWhisperTranscriptionService(model="base")
    service._model = FakeWhisperModel()
    text = await service.transcribe(
        data=b"fake-audio",
        filename="voice.ogg",
        mime_type="audio/ogg",
    )
    assert text == "你好，FlowAgent。"
