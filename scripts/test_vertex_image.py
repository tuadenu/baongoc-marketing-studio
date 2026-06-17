from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils import load_config, ensure_app_dirs, root_path
from src.vertex_client import VertexClient


def main() -> None:
    ensure_app_dirs()
    config = load_config()
    model = config["vertex"]["models"]["image_standard"]
    client = VertexClient(
        project_id=config["project_id"],
        region=config["region"],
        imagen_model=model,
        veo_model=config["vertex"]["models"]["video_standard"],
        api_key=None,
    )
    prompt = "A premium Vietnamese HSK learning app promo poster, vertical marketing art, clean design."
    output_dir = root_path("outputs", "images", "test")
    out = client.generate_image(prompt=prompt, model=model, aspect_ratio="1:1", output_dir=str(output_dir))
    print(f"Output path: {out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise
