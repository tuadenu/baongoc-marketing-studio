from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils import load_config
from src.vertex_client import VertexClient


def _collect_models(config: dict) -> dict[str, list[tuple[str, str]]]:
    vertex_models = config.get("vertex", {}).get("models", {})
    groups = {
        "image_text_models": [
            ("Imagen 4 Fast", vertex_models.get("image_fast", "")),
            ("Imagen 4", vertex_models.get("image_standard", "")),
            ("Imagen 4 Ultra", vertex_models.get("image_ultra", "")),
        ],
        "image_edit_models": [
            ("Nano Banana", vertex_models.get("image_edit_nano_banana", "")),
            ("Nano Banana Pro", vertex_models.get("image_edit_nano_banana_pro", "")),
            ("Gemini image edit", vertex_models.get("image_edit_gemini", "")),
        ],
        "video_models": [
            ("Veo 3.1 Lite", vertex_models.get("video_lite", "")),
            ("Veo 3.1", vertex_models.get("video_standard", "")),
        ],
    }
    return groups


def main() -> None:
    config = load_config()
    project_id = config.get("project_id") or config.get("vertex", {}).get("project_ids", [None])[0]
    region = config.get("region") or config.get("vertex", {}).get("regions", [None])[0] or "us-central1"
    client = VertexClient(
        project_id=project_id,
        region=region,
        imagen_model=config["vertex"]["models"].get("image_standard", ""),
        veo_model=config["vertex"]["models"].get("video_standard", ""),
        api_key=None,
    )

    print(f"project_id={project_id}")
    print(f"region={region}")
    print("== SDK model list ==")
    try:
        pager = client._genai_client().models.list()
        for model in pager:
            name = getattr(model, "name", "")
            display_name = getattr(model, "display_name", "") or getattr(model, "displayName", "")
            print(f"- {name} | {display_name}")
    except Exception as exc:
        print(f"[list_models_error] {exc}")

    print("\n== Config validation ==")
    try:
        available = set()
        pager = client._genai_client().models.list()
        for model in pager:
            name = getattr(model, "name", "")
            if name:
                available.add(name)
            short = name.split("/")[-1] if name else ""
            if short:
                available.add(short)
    except Exception:
        available = set()

    for group_name, items in _collect_models(config).items():
        print(f"\n[{group_name}]")
        for label, model_id in items:
            if not model_id:
                print(f"- {label}: CHƯA CẤU HÌNH")
                continue
            if available and model_id not in available:
                print(f"- {label}: LỖI / {model_id} (không thấy trong list models)")
            else:
                print(f"- {label}: OK / {model_id}")


if __name__ == "__main__":
    main()
