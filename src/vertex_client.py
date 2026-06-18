from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from urllib.parse import urlparse

from .utils import root_path


@dataclass
class VertexAuth:
    project_id: str | None
    region: str | None
    api_key: str | None = None
    credentials: Any | None = None


class VertexClient:
    def __init__(
        self,
        project_id: str,
        region: str,
        imagen_model: str,
        veo_model: str,
        api_key: str | None = None,
    ):
        self.project_id = project_id
        self.region = region
        self.imagen_model = imagen_model
        self.veo_model = veo_model
        self.api_key = api_key
        self._auth = self._resolve_auth()
        self._client = None

    def _resolve_auth(self) -> VertexAuth:
        try:
            import google.auth

            credentials, _ = google.auth.default()
            return VertexAuth(project_id=self.project_id, region=self.region, credentials=credentials)
        except Exception:
            if self.api_key:
                return VertexAuth(project_id=self.project_id, region=self.region, api_key=self.api_key)
            raise RuntimeError("Thiếu thông tin xác thực Google Cloud. Hãy chạy `gcloud auth application-default login`.")

    def _genai_client(self):
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except Exception as exc:
            raise RuntimeError("Missing google-genai package. Install dependencies first.") from exc

        if self._auth.api_key:
            self._client = genai.Client(api_key=self._auth.api_key)
        else:
            self._client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.region,
                credentials=self._auth.credentials,
            )
        return self._client

    def _ensure_dir(self, rel_dir: str) -> Path:
        out = root_path(rel_dir)
        out.mkdir(parents=True, exist_ok=True)
        return out

    def _save_response_bytes(self, payload: Any, out_path: Path) -> None:
        if isinstance(payload, (bytes, bytearray)):
            out_path.write_bytes(payload)
            return
        if hasattr(payload, "read"):
            out_path.write_bytes(payload.read())
            return
        if isinstance(payload, str):
            parsed = urlparse(payload)
            if parsed.scheme in {"http", "https"}:
                from urllib.request import urlopen

                out_path.write_bytes(urlopen(payload).read())
                return
        raise RuntimeError("Không đọc được dữ liệu đầu ra từ Vertex AI.")

    def _load_image_bytes(self, image_path: str) -> tuple[bytes, str]:
        suffix = Path(image_path).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        mime_type = mime_map.get(suffix, "image/png")
        return Path(image_path).read_bytes(), mime_type

    def _extract_uri(self, obj: Any) -> str | None:
        for attr in ["uri", "gcs_uri", "url"]:
            if hasattr(obj, attr):
                value = getattr(obj, attr)
                if value:
                    return str(value)
        return None

    def _first_item(self, response: Any, attr_names: list[str]) -> Any | None:
        for attr in attr_names:
            value = getattr(response, attr, None)
            if value:
                return value[0]
        return None

    def _walk_for_video_like(self, value: Any, seen: set[int] | None = None) -> Any | None:
        if seen is None:
            seen = set()
        if value is None:
            return None
        obj_id = id(value)
        if obj_id in seen:
            return None
        seen.add(obj_id)

        if isinstance(value, (bytes, bytearray)):
            return value
        if hasattr(value, "save"):
            return value
        if isinstance(value, str):
            if value.startswith("gs://") or value.startswith("http://") or value.startswith("https://"):
                return value
            return None

        uri = self._extract_uri(value)
        if uri:
            return uri

        for attr in ("video", "videos", "generated_videos", "results", "response", "output", "uri", "content"):
            nested = getattr(value, attr, None)
            if nested is None:
                continue
            if isinstance(nested, (list, tuple)):
                for item in nested:
                    found = self._walk_for_video_like(item, seen)
                    if found is not None:
                        return found
            else:
                found = self._walk_for_video_like(nested, seen)
                if found is not None:
                    return found

        if isinstance(value, (list, tuple)):
            for item in value:
                found = self._walk_for_video_like(item, seen)
                if found is not None:
                    return found

        if hasattr(value, "__dict__"):
            for nested in value.__dict__.values():
                found = self._walk_for_video_like(nested, seen)
                if found is not None:
                    return found
        return None

    def _poll_operation(self, operation: Any, timeout_seconds: int = 900) -> Any:
        if not hasattr(operation, "done"):
            return operation
        deadline = time.time() + timeout_seconds
        latest = operation
        while not bool(getattr(latest, "done", False)):
            if time.time() >= deadline:
                raise RuntimeError("Hết thời gian chờ Vertex video generation.")
            time.sleep(2)
            name = getattr(latest, "name", None)
            if not name:
                break
            latest = self._genai_client().operations.get(latest)
        return latest

    def _response_from_operation(self, operation: Any) -> Any:
        if hasattr(operation, "response") and operation.response is not None:
            return operation.response
        if hasattr(operation, "result") and operation.result is not None and not callable(operation.result):
            return operation.result
        if hasattr(operation, "result") and callable(operation.result):
            return operation.result()
        return operation

    def generate_image(self, prompt: str, model: str, aspect_ratio: str, output_dir: str) -> str:
        client = self._genai_client()
        out_dir = self._ensure_dir(output_dir)
        filename = f"image_{len(list(out_dir.glob('*.png'))) + 1}.png"
        out_path = out_dir / filename

        try:
            result = client.models.generate_images(
                model=model,
                prompt=prompt,
                config={"aspect_ratio": aspect_ratio},
            )
        except Exception as exc:
            raise RuntimeError(self._format_error(exc)) from exc

        image_obj = self._first_item(result, ["generated_images", "images"])
        if image_obj is None:
            raise RuntimeError("Vertex AI không trả về ảnh.")

        candidate = getattr(image_obj, "image", image_obj)
        if hasattr(candidate, "save"):
            candidate.save(str(out_path))
        else:
            uri = self._extract_uri(candidate)
            if uri:
                self._save_response_bytes(uri, out_path)
            else:
                self._save_response_bytes(candidate, out_path)
        return str(out_path)

    def generate_image_from_reference(
        self,
        prompt: str,
        model: str,
        aspect_ratio: str,
        reference_image_path: str,
        output_dir: str,
        negative_prompt: str | None = None,
        keep_face: bool = True,
        num_images: int = 1,
    ) -> list[str]:
        client = self._genai_client()
        out_dir = self._ensure_dir(output_dir)
        from google.genai import types

        image_bytes, mime_type = self._load_image_bytes(reference_image_path)
        ref_image = types.Image(imageBytes=image_bytes, mimeType=mime_type)
        reference = types.SubjectReferenceImage(
            referenceImage=ref_image,
            config=types.SubjectReferenceConfig(
                subjectType=types.SubjectReferenceType.SUBJECT_TYPE_PERSON,
                subjectDescription="Giữ gương mặt, tóc, dáng người và phong cách nhân vật gần nhất có thể so với ảnh gốc.",
            ),
        )
        edit_config = types.EditImageConfig(
            aspectRatio=aspect_ratio,
            negativePrompt=negative_prompt,
            numberOfImages=num_images,
            editMode=types.EditMode.EDIT_MODE_CONTROLLED_EDITING,
        )

        try:
            response = client.models.edit_image(
                model=model,
                prompt=prompt,
                reference_images=[reference],
                config=edit_config,
            )
        except Exception as exc:
            raise RuntimeError("Model hiện tại chưa hỗ trợ sửa ảnh từ ảnh gốc. Vui lòng dùng model image editing thật.") from exc
        candidate = self._first_item(response, ["generatedImages", "generated_images", "images"])
        if candidate is None:
            raise RuntimeError(f"Vertex AI không trả về ảnh. Response type: {type(response)!r}")
        image_obj = getattr(candidate, "image", candidate)
        out_path = out_dir / f"image_{len(list(out_dir.glob('*.png'))) + 1}.png"
        if hasattr(image_obj, "save"):
            image_obj.save(str(out_path))
        else:
            uri = self._extract_uri(image_obj)
            if uri:
                self._save_response_bytes(uri, out_path)
            else:
                self._save_response_bytes(image_obj, out_path)
        print(
            f"project={self.project_id} region={self.region} model={model} aspect_ratio={aspect_ratio} output_path={out_path}"
        )
        return [str(out_path)]

    def generate_video(
        self,
        prompt: str,
        model: str,
        aspect_ratio: str,
        duration_seconds: int,
        output_dir: str,
        reference_image_path: str | None = None,
        generate_audio: bool = True,
    ) -> str:
        return self.generate_video_with_reference(
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            output_dir=output_dir,
            reference_image_path=reference_image_path,
            generate_audio=generate_audio,
        )

    def generate_video_with_reference(
        self,
        prompt: str,
        model: str,
        aspect_ratio: str,
        duration_seconds: int,
        output_dir: str,
        reference_image_path: str | None = None,
        generate_audio: bool = True,
    ) -> str:
        client = self._genai_client()
        out_dir = self._ensure_dir(output_dir)
        filename = f"video_{len(list(out_dir.glob('*.mp4'))) + 1}.mp4"
        out_path = out_dir / filename
        from google.genai import types
        ref_image = None
        if reference_image_path:
            image_bytes, mime_type = self._load_image_bytes(reference_image_path)
            ref_image = types.Image(imageBytes=image_bytes, mimeType=mime_type)

        config_candidates = []
        if ref_image is not None:
            config_candidates.extend(
                [
                    {"aspectRatio": aspect_ratio, "numberOfVideos": 1, "lastFrame": ref_image, "generateAudio": generate_audio},
                    {"aspectRatio": aspect_ratio, "lastFrame": ref_image, "generateAudio": generate_audio},
                    {"referenceImages": [{"image": ref_image}], "aspectRatio": aspect_ratio, "generateAudio": generate_audio},
                    {"aspectRatio": aspect_ratio, "generateAudio": generate_audio},
                    {},
                ]
            )
        else:
            config_candidates.extend(
                [
                    {"aspectRatio": aspect_ratio, "numberOfVideos": 1, "generateAudio": generate_audio},
                    {"aspectRatio": aspect_ratio, "numberOfResults": 1, "generateAudio": generate_audio},
                    {"aspectRatio": aspect_ratio, "generateAudio": generate_audio},
                    {},
                ]
            )

        operation = None
        last_exc: Exception | None = None
        for config in config_candidates:
            try:
                operation = client.models.generate_videos(
                    model=model,
                    prompt=prompt,
                    config=config,
                )
                break
            except Exception as exc:
                last_exc = exc
                message = str(exc).lower()
                if "extra inputs are not permitted" not in message and "field" not in message:
                    raise RuntimeError(self._format_error(exc)) from exc
        if operation is None:
            raise RuntimeError(self._format_error(last_exc or RuntimeError("Vertex video generation failed.")))

        operation = self._poll_operation(operation)
        response = self._response_from_operation(operation)
        if isinstance(response, dict):
            response = type("VertexResponseDict", (), response)()
        candidate = self._walk_for_video_like(response)
        if candidate is None:
            raise RuntimeError(f"Vertex AI không trả về video. Response type: {type(response)!r}")

        if isinstance(candidate, (bytes, bytearray)):
            out_path.write_bytes(candidate)
        elif hasattr(candidate, "save"):
            candidate.save(str(out_path))
        else:
            uri = self._extract_uri(candidate)
            if uri:
                self._save_response_bytes(uri, out_path)
            else:
                self._save_response_bytes(candidate, out_path)

        print(f"project={self.project_id} region={self.region} model={model} aspect_ratio={aspect_ratio} output_path={out_path}")

        return str(out_path)

    def generate_video_from_image(
        self,
        prompt: str,
        model: str,
        aspect_ratio: str,
        duration_seconds: int,
        image_path: str,
        output_dir: str,
        generate_audio: bool = True,
    ) -> str:
        client = self._genai_client()
        out_dir = self._ensure_dir(output_dir)
        filename = f"video_{len(list(out_dir.glob('*.mp4'))) + 1}.mp4"
        out_path = out_dir / filename

        from google.genai import types

        image_bytes, mime_type = self._load_image_bytes(image_path)
        input_image = types.Image(imageBytes=image_bytes, mimeType=mime_type)

        config_candidates = [
            {
                "aspectRatio": aspect_ratio,
                "durationSeconds": duration_seconds,
                "generateAudio": generate_audio,
                "numberOfVideos": 1,
                "lastFrame": input_image,
            },
            {
                "aspectRatio": aspect_ratio,
                "durationSeconds": duration_seconds,
                "generateAudio": generate_audio,
                "lastFrame": input_image,
            },
            {
                "aspectRatio": aspect_ratio,
                "lastFrame": input_image,
            },
            {},
        ]

        operation = None
        last_exc: Exception | None = None
        for config in config_candidates:
            try:
                operation = client.models.generate_videos(
                    model=model,
                    prompt=prompt,
                    config=config,
                )
                break
            except Exception as exc:
                last_exc = exc
                message = str(exc).lower()
                if "extra inputs are not permitted" not in message and "field" not in message:
                    raise RuntimeError(self._format_error(exc)) from exc
        if operation is None:
            raise RuntimeError(self._format_error(last_exc or RuntimeError("Vertex video generation failed.")))

        operation = self._poll_operation(operation)
        response = self._response_from_operation(operation)
        if isinstance(response, dict):
            response = type("VertexResponseDict", (), response)()
        candidate = self._walk_for_video_like(response)
        if candidate is None:
            raise RuntimeError(f"Vertex AI không trả về video. Response type: {type(response)!r}")

        if isinstance(candidate, (bytes, bytearray)):
            out_path.write_bytes(candidate)
        elif hasattr(candidate, "save"):
            candidate.save(str(out_path))
        else:
            uri = self._extract_uri(candidate)
            if uri:
                self._save_response_bytes(uri, out_path)
            else:
                self._save_response_bytes(candidate, out_path)

        print(
            f"project={self.project_id} region={self.region} model={model} aspect_ratio={aspect_ratio} output_path={out_path}"
        )
        return str(out_path)

    def _format_error(self, exc: Exception) -> str:
        message = str(exc)
        lower = message.lower()
        if "safety" in lower or "blocked" in lower:
            return "Bị chặn bởi chính sách an toàn của Vertex AI."
        if "permission" in lower or "unauthorized" in lower or "auth" in lower:
            return "Thiếu thông tin xác thực Google Cloud."
        if "quota" in lower or "billing" in lower or "payment" in lower:
            return "Lỗi quota hoặc billing trên Google Cloud."
        if "model" in lower and "not" in lower:
            return "Chưa cấu hình model hoặc model không tồn tại."
        return f"Lỗi Vertex AI: {message}"
