import asyncio
import os
from pathlib import Path
import tempfile
from typing import Protocol

import httpx


class TranscriptionService(Protocol):
    @property
    def configured(self) -> bool: ...

    async def transcribe(
        self, *, data: bytes, filename: str, mime_type: str | None = None
    ) -> str: ...


class LocalWhisperTranscriptionService:
    """Lazy, CPU-friendly local transcription; audio never leaves the server."""

    def __init__(
        self,
        *,
        model: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.model_name)

    async def transcribe(
        self, *, data: bytes, filename: str, mime_type: str | None = None
    ) -> str:
        del mime_type
        suffix = Path(filename).suffix or ".ogg"
        async with self._lock:
            return await asyncio.to_thread(self._transcribe_sync, data, suffix)

    def _transcribe_sync(self, data: bytes, suffix: str) -> str:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("本地语音转写模块未安装") from exc
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(data)
                path = handle.name
            segments, _ = self._model.transcribe(
                path,
                beam_size=3,
                vad_filter=True,
            )
            text = "".join(segment.text for segment in segments).strip()
        finally:
            if path:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
        if not text:
            raise RuntimeError("没有从语音中识别到有效文本")
        return text


class OpenAICompatibleTranscriptionService:
    """Small adapter for providers exposing POST /audio/transcriptions."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    async def transcribe(
        self, *, data: bytes, filename: str, mime_type: str | None = None
    ) -> str:
        if not self.configured:
            raise RuntimeError("语音转写服务尚未配置")
        safe_name = Path(filename).name or "audio.ogg"
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={"model": self.model},
                files={"file": (safe_name, data, mime_type or "application/octet-stream")},
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                await client.aclose()
        text = str(payload.get("text") or "").strip()
        if not text:
            raise RuntimeError("语音转写服务没有返回文本")
        return text
