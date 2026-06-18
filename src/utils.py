from __future__ import annotations

from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]


def ensure_app_dirs() -> None:
    for rel in ["data", "outputs/images", "outputs/videos", "outputs/qr", "exports/final", "exports/qr_images", "exports/qr_videos"]:
        (ROOT / rel).mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    for candidate in [ROOT / "config.yaml", ROOT / "config.example.yaml"]:
        if candidate.exists():
            return yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    return {}


def root_path(*parts: str) -> Path:
    return ROOT.joinpath(*parts)
