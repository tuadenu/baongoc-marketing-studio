from __future__ import annotations

import hashlib
import base64
import io
import math
import shutil
import subprocess
import textwrap
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.elements.image as st_image
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .database import get_ui_state, log_request, log_usage_cost, save_ui_state, update_request_status
from .utils import root_path


if not hasattr(st_image, "image_to_url"):
    def _compat_image_to_url(image, width, clamp, channels, output_format, image_id):  # noqa: ANN001
        try:
            import base64 as _base64
            import io as _io

            if isinstance(image, Image.Image):
                buf = _io.BytesIO()
                fmt = (output_format or "PNG").upper()
                image.save(buf, format=fmt)
                mime = "image/png" if fmt == "PNG" else f"image/{fmt.lower()}"
                return f"data:{mime};base64,{_base64.b64encode(buf.getvalue()).decode('ascii')}"
        except Exception:
            pass
        return ""

    st_image.image_to_url = _compat_image_to_url


QR_TARGET_TYPES = {
    "Link app Android": "app_android",
    "Link Zalo": "zalo",
    "Số điện thoại": "phone",
    "Website / Landing page": "website",
    "Nội dung tùy chỉnh": "custom",
}

QR_POSITIONS = ["top_left", "top_right", "bottom_left", "bottom_right"]
QR_THEMES = ["Nền tối", "Nền sáng", "Nền gradient đơn giản"]
QR_TARGET_LABELS = list(QR_TARGET_TYPES.keys())


def _ensure_dir(*parts: str) -> Path:
    out = root_path(*parts)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _slugify(text: str) -> str:
    text = text.lower().strip()
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-", "_"}:
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:80] or "qr"


def _state_hash(*parts: str) -> str:
    return hashlib.md5("::".join(parts).encode("utf-8")).hexdigest()[:10]


def _normalize_target_value(target_type: str, value: str) -> str:
    raw = value.strip()
    if target_type == "phone" and raw and not raw.startswith("tel:"):
        return f"tel:{raw}"
    return raw


def _is_drag_mode(position_mode: str) -> bool:
    return str(position_mode).strip().lower() in {"custom", "drag", "free", "freeform"}


def _canvas_background_image(source_path: str) -> Image.Image | None:
    path = Path(source_path)
    if not path.exists():
        return None
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        try:
            return ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        except Exception:
            return None
    if suffix in {".mp4", ".mov", ".m4v", ".webm"} and ffmpeg_available():
        frame_path = Path(tempfile.gettempdir()) / f"hsk_qr_canvas_{_state_hash(str(path))}.png"
        if not frame_path.exists():
            try:
                _run(["ffmpeg", "-y", "-i", str(path), "-frames:v", "1", str(frame_path)])
            except Exception:
                return None
        if frame_path.exists():
            try:
                return Image.open(frame_path).convert("RGB")
            except Exception:
                return None
    return None


def _fit_canvas_size(width: int, height: int, max_width: int = 900, max_height: int = 700) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return max_width, max_height
    scale = min(max_width / width, max_height / height, 1.0)
    return max(240, int(width * scale)), max(240, int(height * scale))


def _qr_canvas_initial_drawing(
    qr_card: Image.Image | None,
    canvas_width: int,
    canvas_height: int,
    size_percent: int,
    custom_x_percent: int,
    custom_y_percent: int,
    lock_ratio: bool,
) -> dict:
    left = int(canvas_width * custom_x_percent / 100)
    top = int(canvas_height * custom_y_percent / 100)
    if qr_card is None:
        qr_size = max(64, int(canvas_width * size_percent / 100))
        return {
            "version": "4.4.0",
            "objects": [
                {
                    "type": "rect",
                    "version": "4.4.0",
                    "left": left,
                    "top": top,
                    "width": qr_size,
                    "height": qr_size,
                    "fill": "rgba(255, 77, 77, 0.18)",
                    "stroke": "#ff4d4f",
                    "strokeWidth": 3,
                    "originX": "left",
                    "originY": "top",
                    "scaleX": 1,
                    "scaleY": 1,
                    "angle": 0,
                    "selectable": True,
                    "evented": True,
                    "hasBorders": True,
                    "hasControls": True,
                    "transparentCorners": False,
                    "lockUniScaling": bool(lock_ratio),
                }
            ],
        }

    buffer = io.BytesIO()
    qr_card.save(buffer, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    preview_width = max(120, int(canvas_width * size_percent / 100))
    preview_scale = preview_width / max(1, qr_card.width)
    preview_height = max(120, int(qr_card.height * preview_scale))
    return {
        "version": "4.4.0",
        "objects": [
            {
                "type": "image",
                "version": "4.4.0",
                "left": left,
                "top": top,
                "width": qr_card.width,
                "height": qr_card.height,
                "scaleX": preview_scale,
                "scaleY": preview_scale,
                "angle": 0,
                "originX": "left",
                "originY": "top",
                "selectable": True,
                "evented": True,
                "hasBorders": True,
                "hasControls": True,
                "transparentCorners": False,
                "src": data_url,
                "crossOrigin": "anonymous",
                "lockUniScaling": bool(lock_ratio),
            }
        ],
    }


def _render_qr_direct_preview(
    *,
    source_path: str,
    qr_path: str,
    label: str | None,
    white_box: bool,
    label_color: str,
    label_size_percent: int,
    label_bg_color: str,
    label_bg_transparent: bool,
    key: str,
    size_percent: int,
    custom_x_percent: int,
    custom_y_percent: int,
    lock_ratio: bool,
) -> tuple[int, int, float, int, int, str | None]:
    background = _canvas_background_image(source_path)
    if background is None:
        canvas_width, canvas_height = 900, 600
        background = Image.new("RGB", (canvas_width, canvas_height), "white")
        st.warning("Không đọc được ảnh nền, đang hiển thị nền trắng tạm thời.")
    else:
        canvas_width, canvas_height = background.width, background.height
    qr_card = None
    try:
        qr_img = Image.open(qr_path)
        preview_width = max(180, int(canvas_width * size_percent / 100))
        qr_card = _build_qr_card_from_image(qr_img, preview_width, label, white_box, label_color, label_size_percent, label_bg_color, label_bg_transparent)
    except Exception:
        qr_card = None
    if qr_card is None:
        st.warning("Không dựng được preview QR, đang dùng vị trí pixel mặc định.")
        qr_card = Image.new("RGBA", (max(180, int(canvas_width * size_percent / 100)), max(180, int(canvas_width * size_percent / 100))), (255, 255, 255, 255))
    max_x = max(0, canvas_width - qr_card.width)
    max_y = max(0, canvas_height - qr_card.height)
    col1, col2, col3 = st.columns([2.2, 1, 1])
    with col2:
        x_px = st.slider("X px", 0, max_x if max_x > 0 else 0, min(max_x, int(round(canvas_width * custom_x_percent / 100))), key=f"{key}_x_px")
        y_px = st.slider("Y px", 0, max_y if max_y > 0 else 0, min(max_y, int(round(canvas_height * custom_y_percent / 100))), key=f"{key}_y_px")
    with col3:
        st.caption("Debug vị trí")
        st.code(f"X: {x_px}px\nY: {y_px}px\nX: {round(x_px * 100 / max(1, canvas_width))}%\nY: {round(y_px * 100 / max(1, canvas_height))}%")
    preview_path = Path(tempfile.gettempdir()) / f"hsk_qr_preview_{_state_hash(source_path, qr_path, str(x_px), str(y_px), str(size_percent))}.png"
    try:
        overlay_qr_on_image(
            image_path=source_path,
            qr_path=qr_path,
            output_path=str(preview_path),
            position="custom",
            size_percent=float(size_percent),
            margin_percent=0,
            label=None,
            white_box=white_box,
            label_color=label_color,
            label_size_percent=int(label_size_percent),
            label_bg_color=label_bg_color,
            label_bg_transparent=label_bg_transparent,
            x_px=int(x_px),
            y_px=int(y_px),
        )
        preview = Image.open(preview_path).convert("RGBA")
    except Exception:
        preview = background.convert("RGBA").copy()
        preview.alpha_composite(qr_card.convert("RGBA"), dest=(x_px, y_px))
        preview_path = None
    with col1:
        st.image(preview, caption="Preview trên ảnh gốc", use_container_width=True)
        st.caption(f"Source: {source_path}")
        st.caption(f"Size gốc: {canvas_width} x {canvas_height}")
        st.caption(f"Preview file: {preview_path if preview_path is not None else 'fallback in-memory'}")
    return (
        max(0, min(100, int(round(x_px * 100 / max(1, canvas_width))))),
        max(0, min(100, int(round(y_px * 100 / max(1, canvas_height))))),
        1.0,
        x_px,
        y_px,
        str(preview_path) if preview_path is not None else None,
    )


def _default_qr_session(config: dict) -> dict[str, str | int]:
    defaults = config.get("qr_defaults", {})
    target_type = str(defaults.get("default_target_type", "app_android"))
    target_label = next((label for label, value in QR_TARGET_TYPES.items() if value == target_type), "Link app Android")
    return {
        "target_type_label": target_label,
        "target_value": str(defaults.get("default_target_value", "")),
        "label": str(defaults.get("default_label", "Tải app Mẹo Thi HSK")),
        "label_visible": bool(defaults.get("default_label_visible", True)),
        "caption": str(defaults.get("default_caption", "Quét mã QR để tải app và luyện thi HSK ngay")),
        "position": str(defaults.get("default_position", "bottom_right")),
        "position_mode": str(defaults.get("default_position_mode", "preset")),
        "custom_x_percent": int(defaults.get("default_custom_x_percent", 70)),
        "custom_y_percent": int(defaults.get("default_custom_y_percent", 10)),
        "size_percent": int(defaults.get("default_size_percent", 18)),
        "margin_percent": int(defaults.get("default_margin_percent", 4)),
        "label_color": str(defaults.get("default_label_color", "#1f2937")),
        "label_size_percent": int(defaults.get("default_label_size_percent", 10)),
        "label_bg_color": str(defaults.get("default_label_bg_color", "#ffffff")),
        "label_bg_transparent": bool(defaults.get("default_label_bg_transparent", True)),
        "outer_label": str(defaults.get("default_outer_label", "Mẹo Thi HSK Android")),
        "outer_label_visible": bool(defaults.get("default_outer_label_visible", True)),
        "outer_label_color": str(defaults.get("default_outer_label_color", "#e11d48")),
        "outer_label_size_percent": int(defaults.get("default_outer_label_size_percent", 9)),
        "outer_label_bg_color": str(defaults.get("default_outer_label_bg_color", "#ffffff")),
        "outer_label_bg_transparent": bool(defaults.get("default_outer_label_bg_transparent", True)),
        "end_screen_seconds": int(defaults.get("default_end_screen_seconds", 4)),
        "end_screen_title": str(defaults.get("default_end_screen_title", "Tải app Mẹo Thi HSK")),
        "end_screen_subtitle": str(defaults.get("default_end_screen_subtitle", "Quét mã QR để học HSK hiệu quả hơn mỗi ngày")),
        "end_screen_footer": str(defaults.get("default_end_screen_footer", "meothihsk.vn")),
        "qr_path": "",
    }


def _load_last_qr_session(config: dict) -> dict[str, str | int]:
    base = _default_qr_session(config)
    for key, default_value in list(base.items()):
        raw = get_ui_state(f"qr_last_{key}", str(default_value))
        if key in {"size_percent", "margin_percent", "label_size_percent", "outer_label_size_percent", "custom_x_percent", "custom_y_percent", "end_screen_seconds"}:
            try:
                base[key] = int(raw or default_value)
            except Exception:
                base[key] = default_value
        elif key in {"label_bg_transparent", "outer_label_bg_transparent", "label_visible", "outer_label_visible"}:
            base[key] = str(raw).lower() in {"1", "true", "yes", "on"}
        else:
            base[key] = raw if raw is not None else default_value
    qr_path = str(base.get("qr_path", "") or "")
    if qr_path and not Path(qr_path).exists():
        base["qr_path"] = ""
    return base


def _save_last_qr_session(data: dict[str, str | int]) -> None:
    for key, value in data.items():
        save_ui_state(f"qr_last_{key}", str(value))


def _build_qr_from_session(session_data: dict[str, str | int]) -> str:
    target_type_label = str(session_data.get("target_type_label", "Link app Android"))
    target_type = QR_TARGET_TYPES.get(target_type_label, "app_android")
    target_value = _normalize_target_value(target_type, str(session_data.get("target_value", "")))
    label = str(session_data.get("label", "") or "")
    if not target_value:
        raise RuntimeError("Chưa có link hoặc nội dung QR/CTA. Hãy vào tab QR / CTA để tạo hoặc điền trực tiếp trong tab hiện tại.")
    qr_dir = _ensure_dir("outputs", "qr", datetime.now().strftime("%Y%m%d"))
    slug = _slugify(target_value or label)
    qr_path = generate_qr_code(
        target_value,
        str(qr_dir / f"qr_{slug}.png"),
        label=label if bool(session_data.get("label_visible", True)) else None,
        label_color=str(session_data.get("label_color", "#1f2937")),
        label_size_percent=int(session_data.get("label_size_percent", 10)),
        label_bg_color=str(session_data.get("label_bg_color", "#ffffff")),
        label_bg_transparent=bool(session_data.get("label_bg_transparent", True)),
    )
    session_data["qr_path"] = qr_path
    _save_last_qr_session(session_data)
    return qr_path


def render_pre_generate_qr_controls(
    config: dict,
    state_prefix: str,
    media_kind: str,
    allow_end_screen: bool = False,
) -> dict[str, object]:
    defaults = config.get("qr_defaults", {})
    last_session = _load_last_qr_session(config)
    source_hash = _state_hash(state_prefix, media_kind, "pre")
    enabled = st.checkbox("Co them qr/cta vao hay khong?", key=f"{state_prefix}_pre_enable_{source_hash}")
    if not enabled:
        return {"enabled": False}

    target_type_label = st.selectbox(
        "Loai QR / CTA",
        QR_TARGET_LABELS,
        index=QR_TARGET_LABELS.index(str(last_session.get("target_type_label", "Link app Android")))
        if str(last_session.get("target_type_label", "Link app Android")) in QR_TARGET_LABELS
        else 0,
        key=f"{state_prefix}_pre_target_type_{source_hash}",
    )
    target_value = st.text_input(
        "Link / so dien thoai / noi dung QR",
        value=str(last_session.get("target_value", defaults.get("default_target_value", ""))),
        key=f"{state_prefix}_pre_target_value_{source_hash}",
    )
    label_value = st.text_input(
        "Label 1 - trong khung QR",
        value=str(last_session.get("label", defaults.get("default_label", "Tải app Mẹo Thi HSK"))),
        key=f"{state_prefix}_pre_label_{source_hash}",
    )
    label_visible = st.checkbox(
        "Hiện label 1 trong khung QR",
        value=bool(last_session.get("label_visible", defaults.get("default_label_visible", True))),
        key=f"{state_prefix}_pre_label_visible_{source_hash}",
    )
    label_cols = st.columns(2)
    with label_cols[0]:
        label_color = st.color_picker(
            "Mau chu label",
            value=str(last_session.get("label_color", defaults.get("default_label_color", "#1f2937"))),
            key=f"{state_prefix}_pre_label_color_{source_hash}",
        )
    with label_cols[1]:
        label_size_percent = st.slider(
            "Co chu label (%)",
            6,
            20,
            int(last_session.get("label_size_percent", defaults.get("default_label_size_percent", 10))),
            key=f"{state_prefix}_pre_label_size_{source_hash}",
        )
    label_bg_cols = st.columns(2)
    with label_bg_cols[0]:
        label_bg_transparent = st.checkbox(
            "Nen trong suot",
            value=bool(last_session.get("label_bg_transparent", defaults.get("default_label_bg_transparent", True))),
            key=f"{state_prefix}_pre_label_bg_transparent_{source_hash}",
        )
    with label_bg_cols[1]:
        label_bg_color = st.color_picker(
            "Mau nen label",
            value=str(last_session.get("label_bg_color", defaults.get("default_label_bg_color", "#ffffff"))),
            key=f"{state_prefix}_pre_label_bg_color_{source_hash}",
            disabled=label_bg_transparent,
        )
    outer_label = st.text_input(
        "Label 2 - ngoài khung QR",
        value=str(last_session.get("outer_label", defaults.get("default_outer_label", "Mẹo Thi HSK Android"))),
        key=f"{state_prefix}_pre_outer_label_{source_hash}",
    )
    outer_label_visible = st.checkbox(
        "Hiện label 2 ngoài khung QR",
        value=bool(last_session.get("outer_label_visible", defaults.get("default_outer_label_visible", True))),
        key=f"{state_prefix}_pre_outer_label_visible_{source_hash}",
    )
    outer_label_cols = st.columns(2)
    with outer_label_cols[0]:
        outer_label_color = st.color_picker(
            "Màu chữ label 2",
            value=str(last_session.get("outer_label_color", defaults.get("default_outer_label_color", "#e11d48"))),
            key=f"{state_prefix}_pre_outer_label_color_{source_hash}",
        )
    with outer_label_cols[1]:
        outer_label_size_percent = st.slider(
            "Cỡ chữ label 2 (%)",
            6,
            20,
            int(last_session.get("outer_label_size_percent", defaults.get("default_outer_label_size_percent", 9))),
            key=f"{state_prefix}_pre_outer_label_size_{source_hash}",
        )
    outer_bg_cols = st.columns(2)
    with outer_bg_cols[0]:
        outer_label_bg_transparent = st.checkbox(
            "Nền label 2 trong suốt",
            value=bool(last_session.get("outer_label_bg_transparent", defaults.get("default_outer_label_bg_transparent", True))),
            key=f"{state_prefix}_pre_outer_label_bg_transparent_{source_hash}",
        )
    with outer_bg_cols[1]:
        outer_label_bg_color = st.color_picker(
            "Màu nền label 2",
            value=str(last_session.get("outer_label_bg_color", defaults.get("default_outer_label_bg_color", "#ffffff"))),
            key=f"{state_prefix}_pre_outer_label_bg_color_{source_hash}",
            disabled=outer_label_bg_transparent,
        )
    position = st.selectbox(
        "Goc dat QR",
        QR_POSITIONS,
        index=QR_POSITIONS.index(str(last_session.get("position", defaults.get("default_position", "bottom_right"))))
        if str(last_session.get("position", defaults.get("default_position", "bottom_right"))) in QR_POSITIONS
        else 3,
        key=f"{state_prefix}_pre_position_{source_hash}",
    )
    position_mode = st.radio(
        "Che do dat vi tri",
        ["Preset", "Tu do (X/Y)"],
        index=0 if str(last_session.get("position_mode", defaults.get("default_position_mode", "preset"))) not in {"custom", "drag"} else 1,
        key=f"{state_prefix}_pre_position_mode_{source_hash}",
        horizontal=True,
    )
    custom_position_cols = st.columns(2)
    with custom_position_cols[0]:
        custom_x_percent = st.slider(
            "Vi tri X (%)",
            0,
            100,
            int(last_session.get("custom_x_percent", defaults.get("default_custom_x_percent", 70))),
            key=f"{state_prefix}_pre_custom_x_{source_hash}",
            disabled=position_mode != "Tu do (X/Y)",
        )
    with custom_position_cols[1]:
        custom_y_percent = st.slider(
            "Vi tri Y (%)",
            0,
            100,
            int(last_session.get("custom_y_percent", defaults.get("default_custom_y_percent", 10))),
            key=f"{state_prefix}_pre_custom_y_{source_hash}",
            disabled=position_mode != "Tu do (X/Y)",
        )
    size_percent = st.slider(
        "Kich co QR (%)",
        8,
        35,
        int(last_session.get("size_percent", defaults.get("default_size_percent", 18))),
        key=f"{state_prefix}_pre_size_{source_hash}",
    )
    margin_percent = st.slider(
        "Margin (%)",
        0,
        12,
        int(last_session.get("margin_percent", defaults.get("default_margin_percent", 4))),
        key=f"{state_prefix}_pre_margin_{source_hash}",
    )
    white_box = st.checkbox("Nen trang bo goc", value=True, key=f"{state_prefix}_pre_white_box_{source_hash}")
    options: dict[str, object] = {
        "enabled": True,
        "media_kind": media_kind,
        "target_type_label": target_type_label,
        "target_value": _normalize_target_value(QR_TARGET_TYPES.get(target_type_label, "app_android"), target_value),
        "label": label_value,
        "label_visible": bool(label_visible),
        "label_color": label_color,
        "label_size_percent": int(label_size_percent),
        "label_bg_color": label_bg_color,
        "label_bg_transparent": bool(label_bg_transparent),
        "outer_label": outer_label,
        "outer_label_visible": bool(outer_label_visible),
        "outer_label_color": outer_label_color,
        "outer_label_size_percent": int(outer_label_size_percent),
        "outer_label_bg_color": outer_label_bg_color,
        "outer_label_bg_transparent": bool(outer_label_bg_transparent),
        "position": position,
        "position_mode": "custom" if position_mode == "Tu do (X/Y)" else "preset",
        "custom_x_percent": int(custom_x_percent),
        "custom_y_percent": int(custom_y_percent),
        "size_percent": int(size_percent),
        "margin_percent": int(margin_percent),
        "white_box": bool(white_box),
        "end_screen_enabled": False,
        "end_screen_seconds": int(last_session.get("end_screen_seconds", defaults.get("default_end_screen_seconds", 4))),
        "end_screen_title": str(last_session.get("end_screen_title", defaults.get("default_end_screen_title", "Tải app Mẹo Thi HSK"))),
        "end_screen_subtitle": str(last_session.get("end_screen_subtitle", defaults.get("default_end_screen_subtitle", "Quét mã QR để học HSK hiệu quả hơn mỗi ngày"))),
        "end_screen_footer": str(last_session.get("end_screen_footer", defaults.get("default_end_screen_footer", "meothihsk.vn"))),
        "end_screen_theme": "Nền tối",
    }
    try:
        qr_preview_path = _build_qr_from_session(
            {
                "target_type_label": str(options["target_type_label"]),
                "target_value": str(options["target_value"]),
                "label": str(options["label"]),
                "label_visible": bool(options["label_visible"]),
                "label_color": str(options["label_color"]),
                "label_size_percent": int(options["label_size_percent"]),
                "label_bg_color": str(options["label_bg_color"]),
                "label_bg_transparent": bool(options["label_bg_transparent"]),
                "outer_label": str(options["outer_label"]),
                "outer_label_visible": bool(options["outer_label_visible"]),
                "outer_label_color": str(options["outer_label_color"]),
                "outer_label_size_percent": int(options["outer_label_size_percent"]),
                "outer_label_bg_color": str(options["outer_label_bg_color"]),
                "outer_label_bg_transparent": bool(options["outer_label_bg_transparent"]),
                "caption": str(last_session.get("caption", defaults.get("default_caption", "Quét mã QR để tải app và luyện thi HSK ngay"))),
                "position": str(options["position"]),
                "position_mode": str(options["position_mode"]),
                "custom_x_percent": int(options["custom_x_percent"]),
                "custom_y_percent": int(options["custom_y_percent"]),
                "size_percent": int(options["size_percent"]),
                "margin_percent": int(options["margin_percent"]),
                "end_screen_seconds": int(options["end_screen_seconds"]),
                "end_screen_title": str(options["end_screen_title"]),
                "end_screen_subtitle": str(options["end_screen_subtitle"]),
                "end_screen_footer": str(options["end_screen_footer"]),
                "qr_path": str(last_session.get("qr_path", "") or ""),
            }
        )
        options["qr_path"] = qr_preview_path
        st.image(qr_preview_path, caption="QR / CTA se duoc ap dung", width=180)
    except Exception as exc:
        st.warning(str(exc))
        options["enabled"] = False
        return options

    if allow_end_screen and media_kind == "video":
        options["end_screen_enabled"] = st.checkbox("Them qr/cta cuoi video", key=f"{state_prefix}_pre_end_enable_{source_hash}")
        if options["end_screen_enabled"]:
            options["end_screen_seconds"] = st.slider(
                "Thoi luong CTA cuoi video (giay)",
                2,
                10,
                int(last_session.get("end_screen_seconds", defaults.get("default_end_screen_seconds", 4))),
                key=f"{state_prefix}_pre_end_seconds_{source_hash}",
            )
            options["end_screen_title"] = st.text_input(
                "Tieu de CTA cuoi",
                value=str(last_session.get("end_screen_title", defaults.get("default_end_screen_title", "Tải app Mẹo Thi HSK"))),
                key=f"{state_prefix}_pre_end_title_{source_hash}",
            )
            options["end_screen_subtitle"] = st.text_input(
                "Dong noi dung phu",
                value=str(last_session.get("end_screen_subtitle", defaults.get("default_end_screen_subtitle", "Quét mã QR để học HSK hiệu quả hơn mỗi ngày"))),
                key=f"{state_prefix}_pre_end_subtitle_{source_hash}",
            )
            options["end_screen_footer"] = st.text_input(
                "Footer / link / so dien thoai",
                value=str(last_session.get("end_screen_footer", defaults.get("default_end_screen_footer", "meothihsk.vn"))),
                key=f"{state_prefix}_pre_end_footer_{source_hash}",
            )
            options["end_screen_theme"] = st.selectbox(
                "Nen CTA cuoi",
                QR_THEMES,
                index=QR_THEMES.index("Nền tối"),
                key=f"{state_prefix}_pre_end_theme_{source_hash}",
            )
    return options


def apply_qr_cta_pipeline(
    source_path: str,
    config: dict,
    campaign_id: int | None,
    options: dict[str, object] | None,
) -> str:
    if not source_path or not Path(source_path).exists() or not options or not bool(options.get("enabled")):
        return source_path

    session_payload = {
        "target_type_label": str(options.get("target_type_label", "Link app Android")),
        "target_value": str(options.get("target_value", "")),
        "label": str(options.get("label", "")),
        "label_visible": bool(options.get("label_visible", True)),
        "label_color": str(options.get("label_color", "#1f2937")),
        "label_size_percent": int(options.get("label_size_percent", 10)),
        "label_bg_color": str(options.get("label_bg_color", "#ffffff")),
        "label_bg_transparent": bool(options.get("label_bg_transparent", True)),
        "outer_label": str(options.get("outer_label", "")),
        "outer_label_visible": bool(options.get("outer_label_visible", True)),
        "outer_label_color": str(options.get("outer_label_color", "#1f2937")),
        "outer_label_size_percent": int(options.get("outer_label_size_percent", 10)),
        "outer_label_bg_color": str(options.get("outer_label_bg_color", "#ffffff")),
        "outer_label_bg_transparent": bool(options.get("outer_label_bg_transparent", True)),
        "caption": str(_load_last_qr_session(config).get("caption", "")),
        "position": str(options.get("position", "bottom_right")),
        "position_mode": str(options.get("position_mode", "preset")),
        "custom_x_percent": int(options.get("custom_x_percent", 70)),
        "custom_y_percent": int(options.get("custom_y_percent", 10)),
        "size_percent": int(options.get("size_percent", 18)),
        "margin_percent": int(options.get("margin_percent", 4)),
        "end_screen_seconds": int(options.get("end_screen_seconds", 4)),
        "end_screen_title": str(options.get("end_screen_title", "")),
        "end_screen_subtitle": str(options.get("end_screen_subtitle", "")),
        "end_screen_footer": str(options.get("end_screen_footer", "")),
        "qr_path": str(options.get("qr_path", "") or ""),
    }
    qr_path = str(options.get("qr_path", "") or "")
    if not qr_path or not Path(qr_path).exists():
        qr_path = _build_qr_from_session(session_payload)
    _save_last_qr_session(session_payload)

    result_path = source_path
    media_kind = str(options.get("media_kind", "image"))
    if media_kind == "image":
        out_dir = _ensure_dir("exports", "qr_images", datetime.now().strftime("%Y%m%d"))
        out_path = out_dir / f"{_slugify(Path(source_path).stem)}_qr.png"
        overlay_qr_on_image(
            source_path,
            qr_path,
            str(out_path),
            str(options.get("position", "bottom_right")),
            float(options.get("size_percent", 18)),
            float(options.get("margin_percent", 4)),
            label=str(options.get("outer_label", "")) if bool(options.get("outer_label_visible", True)) else None,
            white_box=bool(options.get("white_box", True)),
            label_color=str(options.get("outer_label_color", "#1f2937")),
            label_size_percent=int(options.get("outer_label_size_percent", 10)),
            label_bg_color=str(options.get("outer_label_bg_color", "#ffffff")),
            label_bg_transparent=bool(options.get("outer_label_bg_transparent", True)),
            custom_x_percent=int(options.get("custom_x_percent", 70)) if _is_drag_mode(str(options.get("position_mode", "preset"))) else None,
            custom_y_percent=int(options.get("custom_y_percent", 10)) if _is_drag_mode(str(options.get("position_mode", "preset"))) else None,
        )
        _log_local_request("qr_image_overlay", campaign_id, f"{source_path} | {qr_path}", output_path=str(out_path))
        return str(out_path)

    out_dir = _ensure_dir("exports", "qr_videos", datetime.now().strftime("%Y%m%d"))
    overlay_path = out_dir / f"{_slugify(Path(source_path).stem)}_qr.mp4"
    overlay_qr_on_video(
        source_path,
        qr_path,
        str(overlay_path),
        str(options.get("position", "bottom_right")),
        float(options.get("size_percent", 18)),
        float(options.get("margin_percent", 4)),
        label=str(options.get("outer_label", "")) if bool(options.get("outer_label_visible", True)) else None,
        white_box=bool(options.get("white_box", True)),
        label_color=str(options.get("outer_label_color", "#1f2937")),
        label_size_percent=int(options.get("outer_label_size_percent", 10)),
        label_bg_color=str(options.get("outer_label_bg_color", "#ffffff")),
        label_bg_transparent=bool(options.get("outer_label_bg_transparent", True)),
        custom_x_percent=int(options.get("custom_x_percent", 70)) if _is_drag_mode(str(options.get("position_mode", "preset"))) else None,
        custom_y_percent=int(options.get("custom_y_percent", 10)) if _is_drag_mode(str(options.get("position_mode", "preset"))) else None,
    )
    _log_local_request("qr_video_overlay", campaign_id, f"{source_path} | {qr_path}", output_path=str(overlay_path))
    result_path = str(overlay_path)
    if bool(options.get("end_screen_enabled")):
        final_path = out_dir / f"{_slugify(Path(source_path).stem)}_qr_end.mp4"
        append_qr_end_screen(
            result_path,
            qr_path,
            str(final_path),
            int(options.get("end_screen_seconds", 4)),
            str(options.get("end_screen_title", "Tải app Mẹo Thi HSK")),
            str(options.get("end_screen_subtitle", "Quét mã QR để học HSK hiệu quả hơn mỗi ngày")),
            str(options.get("end_screen_footer", "meothihsk.vn")),
            str(options.get("end_screen_theme", "Nền tối")),
        )
        _log_local_request(
            "qr_end_screen",
            campaign_id,
            f"{options.get('end_screen_title', '')} | {options.get('end_screen_subtitle', '')} | {options.get('end_screen_footer', '')}",
            output_path=str(final_path),
        )
        result_path = str(final_path)
    return result_path


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _hex_to_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        raw = "1f2937"
    try:
        return (
            int(raw[0:2], 16),
            int(raw[2:4], 16),
            int(raw[4:6], 16),
            alpha,
        )
    except Exception:
        return (31, 41, 55, alpha)


def _parse_color(value: str, default: tuple[int, int, int, int] = (255, 255, 255, 0)) -> tuple[int, int, int, int]:
    if not value:
        return default
    raw = value.strip().lower()
    if raw in {"transparent", "none", "trong suot"}:
        return (255, 255, 255, 0)
    if raw.startswith("#") and len(raw) in {7, 9}:
        try:
            red = int(raw[1:3], 16)
            green = int(raw[3:5], 16)
            blue = int(raw[5:7], 16)
            alpha = int(raw[7:9], 16) if len(raw) == 9 else default[3]
            return (red, green, blue, alpha)
        except Exception:
            return default
    return default


def _fit_single_line_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    preferred_size: int,
    min_size: int = 12,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, str]:
    clean = " ".join(text.split())
    if not clean:
        return _font(min_size), ""
    for size in range(max(preferred_size, min_size), min_size - 1, -1):
        candidate = _font(size)
        bbox = draw.textbbox((0, 0), clean, font=candidate)
        if bbox[2] - bbox[0] <= max_width:
            return candidate, clean
    size = min_size
    candidate = _font(size)
    text_value = clean
    while len(text_value) > 1:
        bbox = draw.textbbox((0, 0), text_value + "...", font=candidate)
        if bbox[2] - bbox[0] <= max_width:
            return candidate, text_value + "..."
        text_value = text_value[:-1].rstrip()
    return candidate, clean


def _wrap(text: str, max_chars: int) -> list[str]:
    if not text.strip():
        return []
    lines: list[str] = []
    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        lines.extend(textwrap.wrap(raw_line, width=max_chars) or [raw_line])
    return lines or [text.strip()]


def _probe_video_size(video_path: str) -> tuple[int, int]:
    if not shutil.which("ffprobe"):
        return 1080, 1920
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            video_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = (result.stdout or "").strip()
    if "x" in payload:
        try:
            width, height = payload.split("x", 1)
            return int(width), int(height)
        except Exception:
            pass
    return 1080, 1920


def _probe_image_size(image_path: str) -> tuple[int, int]:
    try:
        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img)
            return img.size
    except Exception:
        return 1080, 1920


def _probe_video_has_audio(video_path: str) -> bool:
    if not shutil.which("ffprobe"):
        return True
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            video_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool((result.stdout or "").strip())


def _qr_base_image(target_value: str) -> Image.Image:
    try:
        import qrcode
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Thiếu thư viện qrcode. Hãy chạy: pip install -r requirements.txt"
        ) from exc
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=4, box_size=12)
    qr.add_data(target_value)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGBA")


def _build_qr_card(
    target_value: str,
    label: str | None,
    target_width: int,
    white_box: bool = True,
    label_color: str = "#1f2937",
    label_size_percent: int = 10,
    label_bg_color: str = "#ffffff",
    label_bg_transparent: bool = True,
) -> Image.Image:
    target_width = max(180, int(target_width))
    qr_img = _qr_base_image(target_value)
    padding = max(16, target_width // 18)
    qr_side = max(120, target_width - padding * 2)
    qr_img = qr_img.resize((qr_side, qr_side), Image.Resampling.LANCZOS)
    label_text = " ".join((label or "").split())
    label_font_size = max(14, int(target_width * max(5, label_size_percent) / 100))
    draw_box = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    label_font, label_text = _fit_single_line_font(draw_box, label_text, max(target_width - 36, 120), label_font_size, min_size=max(12, label_font_size // 2))
    bbox = draw_box.textbbox((0, 0), label_text, font=label_font)
    label_width = bbox[2] - bbox[0]
    label_height = bbox[3] - bbox[1]
    qr_card_h = padding * 2 + qr_side
    label_gap = max(12, target_width // 22) if label_text else 0
    label_pad_x = max(18, target_width // 18)
    label_pad_y = max(12, target_width // 26)
    label_plate_h = label_height + label_pad_y * 2 if label_text else 0
    card_h = qr_card_h + label_gap + label_plate_h
    card = Image.new("RGBA", (target_width, card_h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(card)
    if white_box:
        draw.rounded_rectangle((0, 0, target_width - 1, qr_card_h - 1), radius=max(18, target_width // 12), fill=(255, 255, 255, 255), outline=(230, 230, 230, 255), width=2)
    qr_x = (target_width - qr_side) // 2
    qr_y = padding
    card.alpha_composite(qr_img, dest=(qr_x, qr_y))
    if label_text:
        plate_margin_x = max(8, target_width // 14)
        plate_y = qr_card_h + label_gap
        plate_x = plate_margin_x
        plate_w = target_width - plate_margin_x * 2
        plate_h = label_plate_h
        plate_fill = _parse_color(label_bg_color, (255, 255, 255, 0))
        if label_bg_transparent:
            plate_fill = (255, 255, 255, 0)
        if plate_fill[3] > 0:
            draw.rounded_rectangle(
                (plate_x, plate_y, plate_x + plate_w - 1, plate_y + plate_h - 1),
                radius=max(14, target_width // 16),
                fill=plate_fill,
                outline=(229, 231, 235, 255) if not label_bg_transparent else None,
                width=2 if not label_bg_transparent else 0,
            )
        text_color = _hex_to_rgba(label_color)
        text_x = plate_x + (plate_w - label_width) / 2
        text_y = plate_y + (plate_h - label_height) / 2 - bbox[1]
        draw.text((text_x, text_y), label_text, fill=text_color, font=label_font)
    return card


def generate_qr_code(
    target_value: str,
    output_path: str,
    label: str | None = None,
    label_color: str = "#1f2937",
    label_size_percent: int = 10,
    label_bg_color: str = "#ffffff",
    label_bg_transparent: bool = True,
) -> str:
    card = _build_qr_card(
        target_value,
        label,
        target_width=1024,
        white_box=True,
        label_color=label_color,
        label_size_percent=label_size_percent,
        label_bg_color=label_bg_color,
        label_bg_transparent=label_bg_transparent,
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    card.save(out)
    return str(out)


def _overlay_position(
    base_size: tuple[int, int],
    overlay_size: tuple[int, int],
    position: str,
    margin_percent: float,
    custom_x_percent: float | None = None,
    custom_y_percent: float | None = None,
) -> tuple[int, int]:
    base_w, base_h = base_size
    over_w, over_h = overlay_size
    if position == "custom":
        return int(base_w * float(custom_x_percent or 0) / 100), int(base_h * float(custom_y_percent or 0) / 100)
    margin_x = int(base_w * margin_percent / 100)
    margin_y = int(base_h * margin_percent / 100)
    if position == "top_left":
        return margin_x, margin_y
    if position == "top_right":
        return base_w - over_w - margin_x, margin_y
    if position == "bottom_left":
        return margin_x, base_h - over_h - margin_y
    return base_w - over_w - margin_x, base_h - over_h - margin_y


def _flatten_overlay(
    base_img: Image.Image,
    overlay_img: Image.Image,
    position: str,
    margin_percent: float,
    x_px: int | None = None,
    y_px: int | None = None,
    custom_x_percent: float | None = None,
    custom_y_percent: float | None = None,
) -> Image.Image:
    base = base_img.convert("RGBA")
    overlay = overlay_img.convert("RGBA")
    if x_px is not None and y_px is not None:
        x, y = int(x_px), int(y_px)
    else:
        x, y = _overlay_position(base.size, overlay.size, position, margin_percent, custom_x_percent, custom_y_percent)
    result = base.copy()
    result.alpha_composite(overlay, dest=(max(0, x), max(0, y)))
    return result


def overlay_qr_on_image(
    image_path: str,
    qr_path: str,
    output_path: str,
    position: str,
    size_percent: float,
    margin_percent: float,
    label: str | None = None,
    white_box: bool = True,
    label_color: str = "#1f2937",
    label_size_percent: int = 10,
    label_bg_color: str = "#ffffff",
    label_bg_transparent: bool = True,
    x_px: int | None = None,
    y_px: int | None = None,
    custom_x_percent: float | None = None,
    custom_y_percent: float | None = None,
) -> str:
    base_img = ImageOps.exif_transpose(Image.open(image_path))
    width = base_img.size[0]
    target_width = max(180, int(width * size_percent / 100))
    qr_img = ImageOps.exif_transpose(Image.open(qr_path))
    if label is not None:
        overlay = _build_qr_card_from_image(qr_img, target_width, label, white_box, label_color, label_size_percent, label_bg_color, label_bg_transparent)
    else:
        overlay = _build_qr_card_from_image(qr_img, target_width, None, white_box, label_color, label_size_percent, label_bg_color, label_bg_transparent)
    result = _flatten_overlay(base_img, overlay, position, margin_percent, x_px, y_px, custom_x_percent, custom_y_percent)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    suffix = out.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        result.convert("RGB").save(out, quality=95)
    else:
        result.save(out)
    return str(out)


def _build_qr_card_from_image(
    qr_img: Image.Image,
    target_width: int,
    label: str | None,
    white_box: bool,
    label_color: str = "#1f2937",
    label_size_percent: int = 10,
    label_bg_color: str = "#ffffff",
    label_bg_transparent: bool = True,
) -> Image.Image:
    target_width = max(180, int(target_width))
    padding = max(16, target_width // 18)
    qr_side = max(120, target_width - padding * 2)
    qr_img = qr_img.convert("RGBA").resize((qr_side, qr_side), Image.Resampling.LANCZOS)
    label_text = " ".join((label or "").split())
    label_font_size = max(14, int(target_width * max(5, label_size_percent) / 100))
    draw_box = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    label_font, label_text = _fit_single_line_font(draw_box, label_text, max(target_width - 36, 120), label_font_size, min_size=max(12, label_font_size // 2))
    bbox = draw_box.textbbox((0, 0), label_text, font=label_font)
    label_width = bbox[2] - bbox[0]
    label_height = bbox[3] - bbox[1]
    qr_card_h = padding * 2 + qr_side
    label_gap = max(12, target_width // 22) if label_text else 0
    label_pad_y = max(12, target_width // 26)
    label_plate_h = label_height + label_pad_y * 2 if label_text else 0
    card_h = qr_card_h + label_gap + label_plate_h
    card = Image.new("RGBA", (target_width, card_h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(card)
    if white_box:
        draw.rounded_rectangle((0, 0, target_width - 1, qr_card_h - 1), radius=max(18, target_width // 12), fill=(255, 255, 255, 255), outline=(230, 230, 230, 255), width=2)
    card.alpha_composite(qr_img, dest=((target_width - qr_side) // 2, padding))
    if label_text:
        plate_margin_x = max(8, target_width // 14)
        plate_y = qr_card_h + label_gap
        plate_x = plate_margin_x
        plate_w = target_width - plate_margin_x * 2
        plate_h = label_plate_h
        plate_fill = _parse_color(label_bg_color, (255, 255, 255, 0))
        if label_bg_transparent:
            plate_fill = (255, 255, 255, 0)
        if plate_fill[3] > 0:
            draw.rounded_rectangle(
                (plate_x, plate_y, plate_x + plate_w - 1, plate_y + plate_h - 1),
                radius=max(14, target_width // 16),
                fill=plate_fill,
                outline=(229, 231, 235, 255) if not label_bg_transparent else None,
                width=2 if not label_bg_transparent else 0,
            )
        text_color = _hex_to_rgba(label_color)
        text_x = plate_x + (plate_w - label_width) / 2
        text_y = plate_y + (plate_h - label_height) / 2 - bbox[1]
        draw.text((text_x, text_y), label_text, fill=text_color, font=label_font)
    return card


def overlay_qr_on_video(
    video_path: str,
    qr_path: str,
    output_path: str,
    position: str,
    size_percent: float,
    margin_percent: float,
    label: str | None = None,
    white_box: bool = True,
    label_color: str = "#1f2937",
    label_size_percent: int = 10,
    label_bg_color: str = "#ffffff",
    label_bg_transparent: bool = True,
    x_px: int | None = None,
    y_px: int | None = None,
    custom_x_percent: float | None = None,
    custom_y_percent: float | None = None,
) -> str:
    if not ffmpeg_available():
        raise RuntimeError("Chưa tìm thấy ffmpeg. Hãy cài bằng: brew install ffmpeg")
    width, _ = _probe_video_size(video_path)
    target_width = max(180, int(width * size_percent / 100))
    overlay = _build_qr_card_from_image(ImageOps.exif_transpose(Image.open(qr_path)), target_width, label, white_box, label_color, label_size_percent, label_bg_color, label_bg_transparent)
    temp_overlay = Path(output_path).with_suffix(".overlay.png")
    overlay.save(temp_overlay)
    base_w, base_h = _probe_video_size(video_path)
    over_w, over_h = overlay.size
    if x_px is not None and y_px is not None:
        x, y = int(x_px), int(y_px)
    else:
        x, y = _overlay_position((base_w, base_h), (over_w, over_h), position, margin_percent, custom_x_percent, custom_y_percent)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-i",
            str(temp_overlay),
            "-filter_complex",
            f"[0:v][1:v]overlay={max(0, x)}:{max(0, y)}:format=auto[v]",
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    temp_overlay.unlink(missing_ok=True)
    return str(out)


def _draw_gradient_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    top = (34, 37, 45)
    bottom = (18, 20, 26)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=color)


def create_qr_end_screen(
    width: int,
    height: int,
    qr_path: str,
    output_image_path: str,
    title: str,
    subtitle: str,
    footer: str,
    theme: str,
) -> str:
    bg = Image.new("RGBA", (width, height), (15, 18, 24, 255))
    draw = ImageDraw.Draw(bg)
    if theme == "Nền sáng":
        draw.rectangle((0, 0, width, height), fill=(247, 248, 250, 255))
        fg = (28, 28, 28, 255)
    elif theme == "Nền gradient đơn giản":
        _draw_gradient_background(draw, width, height)
        fg = (255, 255, 255, 255)
    else:
        draw.rectangle((0, 0, width, height), fill=(17, 20, 28, 255))
        fg = (255, 255, 255, 255)
    title_font = _font(max(36, width // 24))
    subtitle_font = _font(max(24, width // 34))
    footer_font = _font(max(20, width // 42))
    qr_width = min(int(width * 0.34), int(height * 0.42))
    qr_overlay = _build_qr_card_from_image(Image.open(qr_path), qr_width, None, True)
    qr_x = width - qr_overlay.size[0] - int(width * 0.08)
    qr_y = (height - qr_overlay.size[1]) // 2
    if theme == "Nền sáng":
        draw.rounded_rectangle((int(width * 0.05), int(height * 0.08), width - int(width * 0.05), height - int(height * 0.08)), radius=36, fill=(255, 255, 255, 255), outline=(230, 230, 230, 255), width=2)
    bg.alpha_composite(qr_overlay, dest=(max(40, qr_x), max(40, qr_y)))
    left_x = int(width * 0.08)
    title_lines = _wrap(title, max_chars=22)
    subtitle_lines = _wrap(subtitle, max_chars=30)
    y = int(height * 0.14)
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        draw.text((left_x, y), line, fill=fg, font=title_font)
        y += (bbox[3] - bbox[1]) + 14
    y += 10
    for line in subtitle_lines:
        bbox = draw.textbbox((0, 0), line, font=subtitle_font)
        draw.text((left_x, y), line, fill=fg, font=subtitle_font)
        y += (bbox[3] - bbox[1]) + 10
    footer_lines = _wrap(footer, max_chars=28)
    footer_y = height - int(height * 0.16)
    for line in footer_lines:
        bbox = draw.textbbox((0, 0), line, font=footer_font)
        draw.text((left_x, footer_y), line, fill=fg, font=footer_font)
        footer_y += (bbox[3] - bbox[1]) + 6
    out = Path(output_image_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.save(out)
    return str(out)


def append_qr_end_screen(
    video_path: str,
    qr_path: str,
    output_path: str,
    duration_seconds: int,
    title: str,
    subtitle: str,
    footer: str,
    theme: str,
) -> str:
    if not ffmpeg_available():
        raise RuntimeError("Chưa tìm thấy ffmpeg. Hãy cài bằng: brew install ffmpeg")
    width, height = _probe_video_size(video_path)
    has_audio = _probe_video_has_audio(video_path)
    out_dir = Path(output_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    end_png = out_dir / f"end_screen_{datetime.now().strftime('%H%M%S')}.png"
    end_mp4 = out_dir / f"end_screen_{datetime.now().strftime('%H%M%S')}.mp4"
    create_qr_end_screen(width, height, qr_path, str(end_png), title, subtitle, footer, theme)
    end_cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(end_png),
        "-t",
        str(duration_seconds),
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
    ]
    if has_audio:
        end_cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest", "-c:a", "aac"])
    else:
        end_cmd.append("-an")
    end_cmd.append(str(end_mp4))
    _run(end_cmd)

    concat_list = out_dir / f"qr_end_concat_{datetime.now().strftime('%H%M%S')}.txt"
    concat_list.write_text("\n".join([f"file '{Path(video_path).as_posix()}'", f"file '{end_mp4.as_posix()}'"]), encoding="utf-8")
    try:
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", output_path])
    except Exception:
        if has_audio:
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    video_path,
                    "-i",
                    str(end_mp4),
                    "-filter_complex",
                    "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    output_path,
                ]
            )
        else:
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    video_path,
                    "-i",
                    str(end_mp4),
                    "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                    "-map",
                    "[v]",
                    "-c:v",
                    "libx264",
                    "-an",
                    output_path,
                ]
            )
    end_png.unlink(missing_ok=True)
    end_mp4.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)
    return str(output_path)


def _qr_source_files() -> list[str]:
    qr_root = root_path("outputs", "qr")
    if not qr_root.exists():
        return []
    return sorted(str(p) for p in qr_root.rglob("*.png"))


def _image_source_files() -> list[str]:
    image_root = root_path("outputs", "images")
    if not image_root.exists():
        return []
    return sorted(str(p) for p in image_root.rglob("*.png")) + sorted(str(p) for p in image_root.rglob("*.jpg")) + sorted(str(p) for p in image_root.rglob("*.jpeg"))


def _video_source_files() -> list[str]:
    roots = [
        root_path("outputs", "videos"),
        root_path("outputs", "long_videos"),
        root_path("exports", "final"),
    ]
    files: list[str] = []
    for root in roots:
        if root.exists():
            files.extend(str(p) for p in root.rglob("*.mp4"))
    return sorted(set(files))


def _save_upload(uploaded_file) -> str:
    target_dir = _ensure_dir("data", "uploads")
    target = target_dir / uploaded_file.name
    target.write_bytes(uploaded_file.read())
    return str(target)


def _render_qr_source_picker(config: dict, state_prefix: str) -> tuple[str | None, str | None]:
    defaults = config.get("qr_defaults", {})
    last_session = _load_last_qr_session(config)
    source_mode = st.radio(
        "Chọn nguồn QR",
        ["QR vừa tạo", "Upload QR PNG", "Tạo QR nhanh từ link nhập trực tiếp"],
        horizontal=True,
        key=f"{state_prefix}_source_mode",
    )
    qr_path: str | None = None
    target_value = ""
    label = defaults.get("default_label", "Tải app Mẹo Thi HSK")
    if source_mode == "QR vừa tạo":
        files = _qr_source_files()
        if files:
            qr_path = st.selectbox("QR đã tạo", files, key=f"{state_prefix}_qr_existing")
        else:
            st.info("Chưa có QR nào được tạo.")
    elif source_mode == "Upload QR PNG":
        uploaded = st.file_uploader("Tải QR PNG lên", type=["png"], key=f"{state_prefix}_qr_upload")
        if uploaded:
            qr_path = _save_upload(uploaded)
    else:
        target_value = st.text_input(
            "Nội dung/link để tạo QR",
            value=defaults.get("default_target_value", ""),
            key=f"{state_prefix}_qr_target_value",
        )
        label = st.text_input(
            "Dòng label ngắn",
            value=defaults.get("default_label", "Tải app Mẹo Thi HSK"),
            key=f"{state_prefix}_qr_label",
        )
        if st.button("Tạo QR nhanh", key=f"{state_prefix}_quick_qr_btn"):
            if not target_value.strip():
                st.error("Vui lòng nhập link hoặc nội dung để tạo QR.")
            else:
                qr_dir = _ensure_dir("outputs", "qr", datetime.now().strftime("%Y%m%d"))
                slug = _slugify(target_value or label)
                qr_path = generate_qr_code(
                    target_value,
                    str(qr_dir / f"qr_{slug}.png"),
                    label=label,
                    label_color=str(last_session.get("label_color", defaults.get("default_label_color", "#1f2937"))),
                    label_size_percent=int(last_session.get("label_size_percent", defaults.get("default_label_size_percent", 10))),
                    label_bg_color=str(last_session.get("label_bg_color", defaults.get("default_label_bg_color", "#ffffff"))),
                    label_bg_transparent=bool(last_session.get("label_bg_transparent", defaults.get("default_label_bg_transparent", True))),
                )
                st.session_state[f"{state_prefix}_latest_qr"] = qr_path
                st.success(f"Đã tạo QR: {qr_path}")
        if st.session_state.get(f"{state_prefix}_latest_qr") and Path(st.session_state[f"{state_prefix}_latest_qr"]).exists():
            qr_path = st.session_state[f"{state_prefix}_latest_qr"]
    return qr_path, label


def _log_local_request(media_type: str, campaign_id: int | None, prompt: str, model: str = "local", output_path: str | None = None, status: str = "completed", detail: str | None = None) -> int:
    request_id = log_request(media_type, campaign_id, detail or prompt, model=model, prompt=prompt, status=status, output_path=output_path)
    log_usage_cost(
        request_id=request_id,
        project_id=str(st.session_state.get("project_id", "") or ""),
        model=model,
        media_type=media_type,
        estimated_cost_usd=0.0,
        estimated_cost_vnd=0.0,
    )
    if status != "completed":
        update_request_status(request_id, status, output_path=output_path, detail=detail)
    return request_id


def render_qr_cta_tab(config: dict, default_campaign_id: int) -> None:
    st.subheader("QR / CTA")
    st.markdown(
        """
        <div style="
            padding: 14px 16px;
            border-radius: 14px;
            background: linear-gradient(90deg, rgba(220,38,38,0.18), rgba(249,115,22,0.16));
            border: 1px solid rgba(239,68,68,0.45);
            color: #fecaca;
            font-weight: 700;
            line-height: 1.45;
            margin: 8px 0 18px 0;
        ">
            QR UI build: <span style="color:#fff">Pixel trực tiếp + QR thuần</span><br/>
            Source: <span style="color:#fff">hsk_marketing_studio/src/qr_tools.py</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    defaults = config.get("qr_defaults", {})
    last_session = _load_last_qr_session(config)

    st.markdown("### A. Tạo QR")
    target_type_label = st.selectbox(
        "Loại QR",
        QR_TARGET_LABELS,
        index=QR_TARGET_LABELS.index(str(last_session.get("target_type_label", "Link app Android")))
        if str(last_session.get("target_type_label", "Link app Android")) in QR_TARGET_LABELS
        else 0,
    )
    target_type = QR_TARGET_TYPES[target_type_label]
    target_value = st.text_input(
        "Nội dung/link để tạo QR",
        value=str(last_session.get("target_value", defaults.get("default_target_value", ""))),
        key="qr_tab_target_value",
    )
    label = st.text_input("Label 1 - trong khung QR", value=str(last_session.get("label", defaults.get("default_label", "Tải app Mẹo Thi HSK"))), key="qr_tab_label")
    label_visible = st.checkbox(
        "Hiện label 1 trong khung QR",
        value=bool(last_session.get("label_visible", defaults.get("default_label_visible", True))),
        key="qr_tab_label_visible",
    )
    caption = st.text_input("Dòng CTA mô tả", value=str(last_session.get("caption", defaults.get("default_caption", "Quét mã QR để tải app và luyện thi HSK ngay"))), key="qr_tab_caption")
    label_cols = st.columns(2)
    with label_cols[0]:
        label_color = st.color_picker(
            "Màu chữ label",
            value=str(last_session.get("label_color", defaults.get("default_label_color", "#1f2937"))),
            key="qr_tab_label_color",
        )
    with label_cols[1]:
        label_size_percent = st.slider(
            "Cỡ chữ label (%)",
            6,
            20,
            int(last_session.get("label_size_percent", defaults.get("default_label_size_percent", 10))),
            key="qr_tab_label_size",
        )
    bg_cols = st.columns(2)
    with bg_cols[0]:
        label_bg_transparent = st.checkbox(
            "Nền trong suốt",
            value=bool(last_session.get("label_bg_transparent", defaults.get("default_label_bg_transparent", True))),
            key="qr_tab_label_bg_transparent",
        )
    with bg_cols[1]:
        label_bg_color = st.color_picker(
            "Màu nền label",
            value=str(last_session.get("label_bg_color", defaults.get("default_label_bg_color", "#ffffff"))),
            key="qr_tab_label_bg_color",
            disabled=label_bg_transparent,
        )
    outer_label = st.text_input(
        "Label 2 - ngoài khung QR",
        value=str(last_session.get("outer_label", defaults.get("default_outer_label", "Mẹo Thi HSK Android"))),
        key="qr_tab_outer_label",
    )
    outer_label_visible = st.checkbox(
        "Hiện label 2 ngoài khung QR",
        value=bool(last_session.get("outer_label_visible", defaults.get("default_outer_label_visible", True))),
        key="qr_tab_outer_label_visible",
    )
    outer_cols = st.columns(2)
    with outer_cols[0]:
        outer_label_color = st.color_picker(
            "Màu chữ label 2",
            value=str(last_session.get("outer_label_color", defaults.get("default_outer_label_color", "#e11d48"))),
            key="qr_tab_outer_label_color",
        )
    with outer_cols[1]:
        outer_label_size_percent = st.slider(
            "Cỡ chữ label 2 (%)",
            6,
            20,
            int(last_session.get("outer_label_size_percent", defaults.get("default_outer_label_size_percent", 9))),
            key="qr_tab_outer_label_size",
        )
    outer_bg_cols = st.columns(2)
    with outer_bg_cols[0]:
        outer_label_bg_transparent = st.checkbox(
            "Nền label 2 trong suốt",
            value=bool(last_session.get("outer_label_bg_transparent", defaults.get("default_outer_label_bg_transparent", True))),
            key="qr_tab_outer_label_bg_transparent",
        )
    with outer_bg_cols[1]:
        outer_label_bg_color = st.color_picker(
            "Màu nền label 2",
            value=str(last_session.get("outer_label_bg_color", defaults.get("default_outer_label_bg_color", "#ffffff"))),
            key="qr_tab_outer_label_bg_color",
            disabled=outer_label_bg_transparent,
        )
    qr_preview_path = st.session_state.get("qr_tab_latest_qr") or str(last_session.get("qr_path", "") or "")
    if st.button("Tạo QR", key="qr_tab_generate_btn"):
        normalized_target = _normalize_target_value(target_type, target_value)
        if not normalized_target:
            st.error("Vui lòng nhập link hoặc nội dung để tạo QR.")
        else:
            qr_dir = _ensure_dir("outputs", "qr", datetime.now().strftime("%Y%m%d"))
            slug = _slugify(normalized_target or label)
            qr_path = generate_qr_code(
                normalized_target,
                str(qr_dir / f"qr_{slug}.png"),
                label=label if label_visible else None,
                label_color=label_color,
                label_size_percent=int(label_size_percent),
                label_bg_color=label_bg_color,
                label_bg_transparent=bool(label_bg_transparent),
            )
            st.session_state["qr_tab_latest_qr"] = qr_path
            qr_preview_path = qr_path
            _save_last_qr_session(
                {
                    "target_type_label": target_type_label,
                    "target_value": normalized_target,
                    "label": label,
                    "label_visible": bool(label_visible),
                    "label_color": label_color,
                    "label_size_percent": int(label_size_percent),
                    "label_bg_color": label_bg_color,
                    "label_bg_transparent": bool(label_bg_transparent),
                    "outer_label": outer_label,
                    "outer_label_visible": bool(outer_label_visible),
                    "outer_label_color": outer_label_color,
                    "outer_label_size_percent": int(outer_label_size_percent),
                    "outer_label_bg_color": outer_label_bg_color,
                    "outer_label_bg_transparent": bool(outer_label_bg_transparent),
                    "caption": caption,
                    "position": str(last_session.get("position", defaults.get("default_position", "bottom_right"))),
                    "position_mode": str(last_session.get("position_mode", defaults.get("default_position_mode", "preset"))),
                    "custom_x_percent": int(last_session.get("custom_x_percent", defaults.get("default_custom_x_percent", 70))),
                    "custom_y_percent": int(last_session.get("custom_y_percent", defaults.get("default_custom_y_percent", 10))),
                    "size_percent": int(last_session.get("size_percent", defaults.get("default_size_percent", 18))),
                    "margin_percent": int(last_session.get("margin_percent", defaults.get("default_margin_percent", 4))),
                    "end_screen_seconds": int(last_session.get("end_screen_seconds", defaults.get("default_end_screen_seconds", 4))),
                    "end_screen_title": str(last_session.get("end_screen_title", defaults.get("default_end_screen_title", "Tải app Mẹo Thi HSK"))),
                    "end_screen_subtitle": str(last_session.get("end_screen_subtitle", defaults.get("default_end_screen_subtitle", "Quét mã QR để học HSK hiệu quả hơn mỗi ngày"))),
                    "end_screen_footer": str(last_session.get("end_screen_footer", defaults.get("default_end_screen_footer", "meothihsk.vn"))),
                    "qr_path": qr_path,
                }
            )
            _log_local_request("qr_generate", default_campaign_id, f"{target_type_label}: {normalized_target}", output_path=qr_path)
            st.success(f"Đã lưu QR tại: {qr_path}")
    if qr_preview_path and Path(qr_preview_path).exists():
        st.image(qr_preview_path, caption="Preview QR", use_container_width=False)
        st.code(qr_preview_path)
        st.caption("Thong tin QR/CTA nay da duoc luu lam phien gan nhat va se duoc nap san o cac tab tao anh/video.")

    st.markdown("### B. Chèn QR vào ảnh")
    image_files = _image_source_files()
    image_choice = st.selectbox("Chọn ảnh", ["Upload ảnh local", *image_files] if image_files else ["Upload ảnh local"], key="qr_image_choice")
    image_path = None
    if image_choice == "Upload ảnh local":
        uploaded = st.file_uploader("Ảnh local", type=["png", "jpg", "jpeg"], key="qr_image_upload")
        if uploaded:
            image_path = _save_upload(uploaded)
    else:
        image_path = image_choice
    if image_path and Path(image_path).exists():
        st.image(image_path, caption="Ảnh gốc", use_container_width=True)
    qr_path, qr_label = _render_qr_source_picker(config, "qr_image")
    position_mode = st.radio(
        "Chế độ vị trí",
        ["Preset", "Tự do (X/Y)", "Pixel trực tiếp"],
        index=0
        if str(last_session.get("position_mode", defaults.get("default_position_mode", "preset"))) not in {"custom", "drag"}
        else (1 if str(last_session.get("position_mode", defaults.get("default_position_mode", "preset"))) == "custom" else 2),
        horizontal=True,
        key="qr_image_position_mode",
    )
    position = st.selectbox(
        "Vị trí",
        QR_POSITIONS,
        index=QR_POSITIONS.index(defaults.get("default_position", "bottom_right")) if defaults.get("default_position", "bottom_right") in QR_POSITIONS else 3,
        key="qr_image_position",
        disabled=position_mode != "Preset",
    )
    size_percent = st.slider("Kích thước QR (% chiều rộng ảnh)", 8, 35, int(defaults.get("default_size_percent", 18)), key="qr_image_size")
    margin_percent = st.slider("Margin (%)", 0, 12, int(defaults.get("default_margin_percent", 4)), key="qr_image_margin")
    white_box = st.checkbox("Nền trắng bo góc sau QR", value=True, key="qr_image_white_box")
    lock_ratio_image = st.checkbox("Khóa tỷ lệ", value=True, key="qr_image_lock_ratio")
    if position_mode == "Pixel trực tiếp":
        _drag_label_image = str(last_session.get("outer_label", defaults.get("default_outer_label", "Mẹo Thi HSK Android")))
        _drag_label_visible_image = bool(last_session.get("outer_label_visible", defaults.get("default_outer_label_visible", True)))
        _drag_label_color_image = str(last_session.get("outer_label_color", defaults.get("default_outer_label_color", "#e11d48")))
        _drag_label_size_image = int(last_session.get("outer_label_size_percent", defaults.get("default_outer_label_size_percent", 9)))
        _drag_label_bg_color_image = str(last_session.get("outer_label_bg_color", defaults.get("default_outer_label_bg_color", "#ffffff")))
        _drag_label_bg_transparent_image = bool(last_session.get("outer_label_bg_transparent", defaults.get("default_outer_label_bg_transparent", True)))
        custom_x_percent, custom_y_percent, drag_scale_image, custom_x_px_image, custom_y_px_image, preview_path_image = _render_qr_direct_preview(
            source_path=image_path or "",
            qr_path=qr_path,
            label=_drag_label_image if _drag_label_visible_image else None,
            white_box=white_box,
            label_color=_drag_label_color_image,
            label_size_percent=_drag_label_size_image,
            label_bg_color=_drag_label_bg_color_image,
            label_bg_transparent=_drag_label_bg_transparent_image,
            key="qr_image_drag_canvas",
            size_percent=int(size_percent),
            custom_x_percent=int(last_session.get("custom_x_percent", defaults.get("default_custom_x_percent", 70))),
            custom_y_percent=int(last_session.get("custom_y_percent", defaults.get("default_custom_y_percent", 10))),
            lock_ratio=bool(lock_ratio_image),
        )
    else:
        drag_scale_image = 1.0
        custom_x_px_image = None
        custom_y_px_image = None
        preview_path_image = None
    outer_label_visible_image = st.checkbox(
        "Hiện label 2 ngoài khung QR",
        value=bool(last_session.get("outer_label_visible", defaults.get("default_outer_label_visible", True))),
        key="qr_image_outer_label_visible",
    )
    outer_label_image = st.text_input(
        "Label 2 - ngoài khung QR",
        value=str(last_session.get("outer_label", defaults.get("default_outer_label", "Mẹo Thi HSK Android"))),
        key="qr_image_outer_label",
    )
    image_label_cols = st.columns(2)
    with image_label_cols[0]:
        qr_image_label_color = st.color_picker(
            "Màu chữ label 2",
            value=str(last_session.get("outer_label_color", defaults.get("default_outer_label_color", "#e11d48"))),
            key="qr_image_label_color",
        )
    with image_label_cols[1]:
        qr_image_label_size = st.slider(
            "Cỡ chữ label 2 (%)",
            6,
            20,
            int(last_session.get("outer_label_size_percent", defaults.get("default_outer_label_size_percent", 9))),
            key="qr_image_label_size",
        )
    image_bg_cols = st.columns(2)
    with image_bg_cols[0]:
        qr_image_label_bg_transparent = st.checkbox(
            "Nền label 2 trong suốt",
            value=bool(last_session.get("outer_label_bg_transparent", defaults.get("default_outer_label_bg_transparent", True))),
            key="qr_image_label_bg_transparent",
        )
    with image_bg_cols[1]:
        qr_image_label_bg_color = st.color_picker(
            "Màu nền label 2",
            value=str(last_session.get("outer_label_bg_color", defaults.get("default_outer_label_bg_color", "#ffffff"))),
            key="qr_image_label_bg_color",
            disabled=qr_image_label_bg_transparent,
        )
    if st.button("Đặt lại vị trí QR", key="qr_image_reset_btn"):
        st.session_state["qr_image_position_mode"] = "Preset"
        st.session_state["qr_image_position"] = defaults.get("default_position", "bottom_right")
        st.session_state["qr_image_custom_x"] = int(defaults.get("default_custom_x_percent", 70))
        st.session_state["qr_image_custom_y"] = int(defaults.get("default_custom_y_percent", 10))
        st.session_state["qr_image_size"] = int(defaults.get("default_size_percent", 18))
        st.rerun()
    if position_mode != "Pixel trực tiếp":
        pos_cols = st.columns(2)
        with pos_cols[0]:
            custom_x_percent = st.slider(
                "X (%)",
                0,
                100,
                int(last_session.get("custom_x_percent", defaults.get("default_custom_x_percent", 70))),
                key="qr_image_custom_x",
                disabled=position_mode != "Tự do (X/Y)",
            )
        with pos_cols[1]:
            custom_y_percent = st.slider(
                "Y (%)",
                0,
                100,
                int(last_session.get("custom_y_percent", defaults.get("default_custom_y_percent", 10))),
                key="qr_image_custom_y",
                disabled=position_mode != "Tự do (X/Y)",
            )
    effective_size_percent_image = int(size_percent)
    if st.button("Xuất ảnh có QR", key="qr_image_export_btn"):
        if not image_path or not Path(image_path).exists():
            st.error("Chưa có ảnh đầu vào.")
        elif not qr_path or not Path(qr_path).exists():
            st.error("Chưa có QR hợp lệ.")
        else:
            out_dir = _ensure_dir("exports", "qr_images", datetime.now().strftime("%Y%m%d"))
            out_path = out_dir / f"{_slugify(Path(image_path).stem)}_qr.png"
            try:
                if position_mode == "Pixel trực tiếp" and preview_path_image and Path(preview_path_image).exists():
                    shutil.copy2(preview_path_image, out_path)
                else:
                    overlay_qr_on_image(
                        image_path=image_path,
                        qr_path=qr_path,
                        output_path=str(out_path),
                        position="custom" if position_mode in {"Tự do (X/Y)", "Pixel trực tiếp"} else position,
                        custom_x_percent=(
                            int(custom_x_percent)
                            if position_mode == "Pixel trực tiếp" and custom_x_percent is not None
                            else int(custom_x_percent) if position_mode == "Tự do (X/Y)" else None
                        ),
                        custom_y_percent=(
                            int(custom_y_percent)
                            if position_mode == "Pixel trực tiếp" and custom_y_percent is not None
                            else int(custom_y_percent) if position_mode == "Tự do (X/Y)" else None
                        ),
                        size_percent=effective_size_percent_image,
                        margin_percent=margin_percent,
                        label=None if position_mode == "Pixel trực tiếp" else (outer_label_image if outer_label_visible_image else None),
                        white_box=white_box,
                        label_color=qr_image_label_color,
                        label_size_percent=int(qr_image_label_size),
                        label_bg_color=qr_image_label_bg_color,
                        label_bg_transparent=bool(qr_image_label_bg_transparent),
                    )
                _log_local_request("qr_image_overlay", default_campaign_id, f"{image_path} | {qr_path}", output_path=str(out_path))
                st.success(f"Đã lưu tại: {out_path}")
                st.image(str(out_path), caption="Ảnh có QR", use_container_width=True)
                st.code(str(out_path))
            except Exception as exc:
                st.error(f"Lỗi chèn QR vào ảnh: {exc}")

    st.markdown("### C. Chèn QR vào video")
    video_files = _video_source_files()
    video_choice = st.selectbox("Chọn video", ["Upload video local", *video_files] if video_files else ["Upload video local"], key="qr_video_choice")
    video_path = None
    if video_choice == "Upload video local":
        uploaded_video = st.file_uploader("Video local", type=["mp4", "mov", "m4v"], key="qr_video_upload")
        if uploaded_video:
            video_path = _save_upload(uploaded_video)
    else:
        video_path = video_choice
    if video_path and Path(video_path).exists():
        st.video(video_path)
    qr_path_video, qr_label_video = _render_qr_source_picker(config, "qr_video")
    position_mode_video = st.radio(
        "Chế độ vị trí QR",
        ["Preset", "Tự do (X/Y)", "Pixel trực tiếp"],
        index=0
        if str(last_session.get("position_mode", defaults.get("default_position_mode", "preset"))) not in {"custom", "drag"}
        else (1 if str(last_session.get("position_mode", defaults.get("default_position_mode", "preset"))) == "custom" else 2),
        horizontal=True,
        key="qr_video_position_mode",
    )
    position_video = st.selectbox(
        "Vị trí QR",
        QR_POSITIONS,
        index=QR_POSITIONS.index(defaults.get("default_position", "bottom_right")) if defaults.get("default_position", "bottom_right") in QR_POSITIONS else 3,
        key="qr_video_position",
        disabled=position_mode_video != "Preset",
    )
    size_percent_video = st.slider("Kích thước QR video (% chiều rộng)", 8, 35, int(defaults.get("default_size_percent", 18)), key="qr_video_size")
    margin_percent_video = st.slider("Margin video (%)", 0, 12, int(defaults.get("default_margin_percent", 4)), key="qr_video_margin")
    white_box_video = st.checkbox("Nền trắng bo góc sau QR", value=True, key="qr_video_white_box")
    lock_ratio_video = st.checkbox("Khóa tỷ lệ", value=True, key="qr_video_lock_ratio")
    outer_label_visible_video = st.checkbox(
        "Hiện label 2 ngoài khung QR",
        value=bool(last_session.get("outer_label_visible", defaults.get("default_outer_label_visible", True))),
        key="qr_video_outer_label_visible",
    )
    outer_label_video = st.text_input(
        "Label 2 - ngoài khung QR",
        value=str(last_session.get("outer_label", defaults.get("default_outer_label", "Mẹo Thi HSK Android"))),
        key="qr_video_outer_label",
    )
    video_label_cols = st.columns(2)
    with video_label_cols[0]:
        qr_video_label_color = st.color_picker(
            "Màu chữ label 2",
            value=str(last_session.get("outer_label_color", defaults.get("default_outer_label_color", "#e11d48"))),
            key="qr_video_label_color",
        )
    with video_label_cols[1]:
        qr_video_label_size = st.slider(
            "Cỡ chữ label 2 (%)",
            6,
            20,
            int(last_session.get("outer_label_size_percent", defaults.get("default_outer_label_size_percent", 9))),
            key="qr_video_label_size",
        )
    video_bg_cols = st.columns(2)
    with video_bg_cols[0]:
        qr_video_label_bg_transparent = st.checkbox(
            "Nền label 2 trong suốt",
            value=bool(last_session.get("outer_label_bg_transparent", defaults.get("default_outer_label_bg_transparent", True))),
            key="qr_video_label_bg_transparent",
        )
    with video_bg_cols[1]:
        qr_video_label_bg_color = st.color_picker(
            "Màu nền label 2",
            value=str(last_session.get("outer_label_bg_color", defaults.get("default_outer_label_bg_color", "#ffffff"))),
            key="qr_video_label_bg_color",
            disabled=qr_video_label_bg_transparent,
        )
    if st.button("Đặt lại vị trí QR", key="qr_video_reset_btn"):
        st.session_state["qr_video_position_mode"] = "Preset"
        st.session_state["qr_video_position"] = defaults.get("default_position", "bottom_right")
        st.session_state["qr_video_custom_x"] = int(defaults.get("default_custom_x_percent", 70))
        st.session_state["qr_video_custom_y"] = int(defaults.get("default_custom_y_percent", 10))
        st.session_state["qr_video_size"] = int(defaults.get("default_size_percent", 18))
        st.rerun()
    if position_mode_video == "Pixel trực tiếp":
        custom_x_percent_video, custom_y_percent_video, drag_scale_video, custom_x_px_video, custom_y_px_video, preview_path_video = _render_qr_direct_preview(
            source_path=video_path or "",
            qr_path=qr_path_video,
            label=None if position_mode_video == "Pixel trực tiếp" else (outer_label_video if outer_label_visible_video else None),
            white_box=white_box_video,
            label_color=qr_video_label_color,
            label_size_percent=int(qr_video_label_size),
            label_bg_color=qr_video_label_bg_color,
            label_bg_transparent=bool(qr_video_label_bg_transparent),
            key="qr_video_drag_canvas",
            size_percent=int(size_percent_video),
            custom_x_percent=int(last_session.get("custom_x_percent", defaults.get("default_custom_x_percent", 70))),
            custom_y_percent=int(last_session.get("custom_y_percent", defaults.get("default_custom_y_percent", 10))),
            lock_ratio=bool(lock_ratio_video),
        )
    else:
        drag_scale_video = 1.0
        custom_x_px_video = None
        custom_y_px_video = None
        preview_path_video = None
        pos_video_cols = st.columns(2)
        with pos_video_cols[0]:
            custom_x_percent_video = st.slider(
                "X (%)",
                0,
                100,
                int(last_session.get("custom_x_percent", defaults.get("default_custom_x_percent", 70))),
                key="qr_video_custom_x",
                disabled=position_mode_video != "Tự do (X/Y)",
            )
        with pos_video_cols[1]:
            custom_y_percent_video = st.slider(
                "Y (%)",
                0,
                100,
                int(last_session.get("custom_y_percent", defaults.get("default_custom_y_percent", 10))),
                key="qr_video_custom_y",
                disabled=position_mode_video != "Tự do (X/Y)",
            )
    effective_size_percent_video = int(size_percent_video)
    if st.button("Xuất video có QR", key="qr_video_export_btn"):
        if not ffmpeg_available():
            st.error("Chưa tìm thấy ffmpeg. Hãy cài bằng: brew install ffmpeg")
        elif not video_path or not Path(video_path).exists():
            st.error("Chưa có video đầu vào.")
        elif not qr_path_video or not Path(qr_path_video).exists():
            st.error("Chưa có QR hợp lệ.")
        else:
            out_dir = _ensure_dir("exports", "qr_videos", datetime.now().strftime("%Y%m%d"))
            out_path = out_dir / f"{_slugify(Path(video_path).stem)}_qr.mp4"
            try:
                if position_mode_video == "Pixel trực tiếp" and preview_path_video and Path(preview_path_video).exists():
                    shutil.copy2(preview_path_video, out_path)
                else:
                    overlay_qr_on_video(
                        video_path=video_path,
                        qr_path=qr_path_video,
                        output_path=str(out_path),
                        position="custom" if position_mode_video in {"Tự do (X/Y)", "Pixel trực tiếp"} else position_video,
                        x_px=int(custom_x_px_video) if custom_x_px_video is not None else None,
                        y_px=int(custom_y_px_video) if custom_y_px_video is not None else None,
                        custom_x_percent=(
                            int(custom_x_percent_video)
                            if position_mode_video == "Pixel trực tiếp" and custom_x_percent_video is not None
                            else int(custom_x_percent_video) if position_mode_video == "Tự do (X/Y)" else None
                        ),
                        custom_y_percent=(
                            int(custom_y_percent_video)
                            if position_mode_video == "Pixel trực tiếp" and custom_y_percent_video is not None
                            else int(custom_y_percent_video) if position_mode_video == "Tự do (X/Y)" else None
                        ),
                        size_percent=effective_size_percent_video,
                        margin_percent=margin_percent_video,
                        label=None if position_mode_video == "Pixel trực tiếp" else (outer_label_video if outer_label_visible_video else None),
                        white_box=white_box_video,
                        label_color=qr_video_label_color,
                        label_size_percent=int(qr_video_label_size),
                        label_bg_color=qr_video_label_bg_color,
                        label_bg_transparent=bool(qr_video_label_bg_transparent),
                    )
                _log_local_request("qr_video_overlay", default_campaign_id, f"{video_path} | {qr_path_video}", output_path=str(out_path))
                st.success(f"Đã lưu tại: {out_path}")
                st.video(str(out_path))
                st.code(str(out_path))
            except Exception as exc:
                st.error(f"Lỗi chèn QR vào video: {exc}")

    st.markdown("### D. Thêm màn hình QR cuối video")
    video_choice_end = st.selectbox("Chọn video cho end screen", ["Upload video local", *video_files] if video_files else ["Upload video local"], key="qr_end_video_choice")
    video_path_end = None
    if video_choice_end == "Upload video local":
        uploaded_end = st.file_uploader("Video local cho end screen", type=["mp4", "mov", "m4v"], key="qr_end_video_upload")
        if uploaded_end:
            video_path_end = _save_upload(uploaded_end)
    else:
        video_path_end = video_choice_end
    qr_path_end, qr_label_end = _render_qr_source_picker(config, "qr_end")
    position_mode_end = st.radio(
        "Chế độ vị trí QR",
        ["Preset", "Tự do (X/Y)"],
        index=0 if str(last_session.get("position_mode", defaults.get("default_position_mode", "preset"))) not in {"custom", "drag"} else 1,
        horizontal=True,
        key="qr_end_position_mode",
    )
    end_pos_cols = st.columns(2)
    with end_pos_cols[0]:
        custom_x_percent_end = st.slider(
            "X (%)",
            0,
            100,
            int(last_session.get("custom_x_percent", defaults.get("default_custom_x_percent", 70))),
            key="qr_end_custom_x",
            disabled=position_mode_end != "Tự do (X/Y)",
        )
    with end_pos_cols[1]:
        custom_y_percent_end = st.slider(
            "Y (%)",
            0,
            100,
            int(last_session.get("custom_y_percent", defaults.get("default_custom_y_percent", 10))),
            key="qr_end_custom_y",
            disabled=position_mode_end != "Tự do (X/Y)",
        )
    duration_seconds = st.slider("Số giây màn hình cuối", 2, 10, int(defaults.get("default_end_screen_seconds", 4)), key="qr_end_duration")
    title = st.text_input("Tiêu đề màn hình cuối", value=defaults.get("default_end_screen_title", "Tải app Mẹo Thi HSK"), key="qr_end_title")
    subtitle = st.text_input("Nội dung phụ", value=defaults.get("default_end_screen_subtitle", "Quét mã QR để học HSK hiệu quả hơn mỗi ngày"), key="qr_end_subtitle")
    footer = st.text_input("Footer / link / số điện thoại", value=defaults.get("default_end_screen_footer", "meothihsk.vn"), key="qr_end_footer")
    theme = st.selectbox("Nền", QR_THEMES, index=QR_THEMES.index("Nền tối"), key="qr_end_theme")
    if st.button("Xuất video có màn hình QR cuối", key="qr_end_export_btn"):
        if not ffmpeg_available():
            st.error("Chưa tìm thấy ffmpeg. Hãy cài bằng: brew install ffmpeg")
        elif not video_path_end or not Path(video_path_end).exists():
            st.error("Chưa có video đầu vào.")
        elif not qr_path_end or not Path(qr_path_end).exists():
            st.error("Chưa có QR hợp lệ.")
        else:
            out_dir = _ensure_dir("exports", "qr_videos", datetime.now().strftime("%Y%m%d"))
            out_path = out_dir / f"{_slugify(Path(video_path_end).stem)}_qr_end.mp4"
            try:
                append_qr_end_screen(
                    video_path=video_path_end,
                    qr_path=qr_path_end,
                    output_path=str(out_path),
                    duration_seconds=duration_seconds,
                    title=title,
                    subtitle=subtitle,
                    footer=footer,
                    theme=theme,
                )
                _log_local_request("qr_end_screen", default_campaign_id, f"{title} | {subtitle} | {footer}", output_path=str(out_path))
                st.success(f"Đã lưu tại: {out_path}")
                st.video(str(out_path))
                st.code(str(out_path))
            except Exception as exc:
                st.error(f"Lỗi tạo màn hình QR cuối video: {exc}")


def render_qr_postprocess_controls(
    source_path: str,
    config: dict,
    media_kind: str,
    campaign_id: int | None,
    state_prefix: str,
    allow_end_screen: bool = False,
) -> None:
    if not source_path or not Path(source_path).exists():
        return
    defaults = config.get("qr_defaults", {})
    last_session = _load_last_qr_session(config)
    source_hash = _state_hash(source_path, media_kind, state_prefix)
    checkbox_label = "Co them QR/CTA vao hay khong?"
    enable = st.checkbox(checkbox_label, key=f"{state_prefix}_qr_enable_{source_hash}")
    if not enable:
        return
    target_type_label = st.selectbox(
        "Loai QR / CTA",
        QR_TARGET_LABELS,
        index=QR_TARGET_LABELS.index(str(last_session.get("target_type_label", "Link app Android")))
        if str(last_session.get("target_type_label", "Link app Android")) in QR_TARGET_LABELS
        else 0,
        key=f"{state_prefix}_target_type_{source_hash}",
    )
    target_value = st.text_input(
        "Link / so dien thoai / noi dung QR",
        value=str(last_session.get("target_value", defaults.get("default_target_value", ""))),
        key=f"{state_prefix}_target_value_{source_hash}",
    )
    label_value = st.text_input(
        "Label 2 - ngoài khung QR",
        value=str(last_session.get("outer_label", defaults.get("default_outer_label", "Mẹo Thi HSK Android"))),
        key=f"{state_prefix}_outer_label_{source_hash}",
    )
    label_visible = st.checkbox(
        "Hiện label 2 ngoài khung QR",
        value=bool(last_session.get("outer_label_visible", defaults.get("default_outer_label_visible", True))),
        key=f"{state_prefix}_outer_label_visible_{source_hash}",
    )
    label_cols = st.columns(2)
    with label_cols[0]:
        label_color = st.color_picker(
            "Mau chu label 2",
            value=str(last_session.get("outer_label_color", defaults.get("default_outer_label_color", "#e11d48"))),
            key=f"{state_prefix}_outer_label_color_{source_hash}",
        )
    with label_cols[1]:
        label_size_percent = st.slider(
            "Co chu label 2 (%)",
            6,
            20,
            int(last_session.get("outer_label_size_percent", defaults.get("default_outer_label_size_percent", 9))),
            key=f"{state_prefix}_outer_label_size_{source_hash}",
        )
    bg_cols = st.columns(2)
    with bg_cols[0]:
        label_bg_transparent = st.checkbox(
            "Nen label 2 trong suot",
            value=bool(last_session.get("outer_label_bg_transparent", defaults.get("default_outer_label_bg_transparent", True))),
            key=f"{state_prefix}_outer_label_bg_transparent_{source_hash}",
        )
    with bg_cols[1]:
        label_bg_color = st.color_picker(
            "Mau nen label 2",
            value=str(last_session.get("outer_label_bg_color", defaults.get("default_outer_label_bg_color", "#ffffff"))),
            key=f"{state_prefix}_outer_label_bg_color_{source_hash}",
            disabled=label_bg_transparent,
        )
    position = st.selectbox(
        "Goc dat QR",
        QR_POSITIONS,
        index=QR_POSITIONS.index(str(last_session.get("position", defaults.get("default_position", "bottom_right"))))
        if str(last_session.get("position", defaults.get("default_position", "bottom_right"))) in QR_POSITIONS
        else 3,
        key=f"{state_prefix}_position_{source_hash}",
    )
    position_mode = st.radio(
        "Che do vi tri",
        ["Preset", "Tu do (X/Y)", "Pixel trực tiếp"],
        index=0
        if str(last_session.get("position_mode", defaults.get("default_position_mode", "preset"))) not in {"custom", "drag"}
        else (1 if str(last_session.get("position_mode", defaults.get("default_position_mode", "preset"))) == "custom" else 2),
        horizontal=True,
        key=f"{state_prefix}_position_mode_{source_hash}",
    )
    size_percent = st.slider(
        "Kich co mac dinh / tuy chon (%)",
        8,
        35,
        int(last_session.get("size_percent", defaults.get("default_size_percent", 18))),
        key=f"{state_prefix}_size_{source_hash}",
    )
    margin_percent = st.slider(
        "Margin (%)",
        0,
        12,
        int(last_session.get("margin_percent", defaults.get("default_margin_percent", 4))),
        key=f"{state_prefix}_margin_{source_hash}",
    )
    if position_mode == "Pixel trực tiếp":
        custom_x_percent, custom_y_percent, _, custom_x_px_image, custom_y_px_image, preview_path_image = _render_qr_direct_preview(
            source_path=source_path,
            qr_path=qr_path,
            label=None if position_mode == "Pixel trực tiếp" else (label_value if label_visible else None),
            white_box=white_box,
            label_color=label_color,
            label_size_percent=int(label_size_percent),
            label_bg_color=label_bg_color,
            label_bg_transparent=bool(label_bg_transparent),
            key=f"{state_prefix}_drag_canvas_{source_hash}",
            size_percent=int(size_percent),
            custom_x_percent=int(last_session.get("custom_x_percent", defaults.get("default_custom_x_percent", 70))),
            custom_y_percent=int(last_session.get("custom_y_percent", defaults.get("default_custom_y_percent", 10))),
        )
    else:
        pos_cols = st.columns(2)
        with pos_cols[0]:
            custom_x_percent = st.slider(
                "Vi tri X (%)",
                0,
                100,
                int(last_session.get("custom_x_percent", defaults.get("default_custom_x_percent", 70))),
                key=f"{state_prefix}_custom_x_{source_hash}",
                disabled=position_mode != "Tu do (X/Y)",
            )
        with pos_cols[1]:
            custom_y_percent = st.slider(
                "Vi tri Y (%)",
                0,
                100,
                int(last_session.get("custom_y_percent", defaults.get("default_custom_y_percent", 10))),
                key=f"{state_prefix}_custom_y_{source_hash}",
                disabled=position_mode != "Tu do (X/Y)",
            )
    white_box = st.checkbox("Nen trang bo goc", value=True, key=f"{state_prefix}_white_box_{source_hash}")
    session_payload = {
        "target_type_label": target_type_label,
        "target_value": _normalize_target_value(QR_TARGET_TYPES.get(target_type_label, "app_android"), target_value),
        "outer_label": label_value,
        "outer_label_visible": bool(label_visible),
        "outer_label_color": label_color,
        "outer_label_size_percent": int(label_size_percent),
        "outer_label_bg_color": label_bg_color,
        "outer_label_bg_transparent": bool(label_bg_transparent),
        "caption": str(last_session.get("caption", defaults.get("default_caption", "Quét mã QR để tải app và luyện thi HSK ngay"))),
        "position": position,
        "position_mode": "drag" if position_mode == "Pixel trực tiếp" else ("custom" if position_mode == "Tu do (X/Y)" else "preset"),
        "custom_x_percent": int(custom_x_percent),
        "custom_y_percent": int(custom_y_percent),
        "size_percent": int(size_percent),
        "margin_percent": int(margin_percent),
        "end_screen_seconds": int(last_session.get("end_screen_seconds", defaults.get("default_end_screen_seconds", 4))),
        "end_screen_title": str(last_session.get("end_screen_title", defaults.get("default_end_screen_title", "Tải app Mẹo Thi HSK"))),
        "end_screen_subtitle": str(last_session.get("end_screen_subtitle", defaults.get("default_end_screen_subtitle", "Quét mã QR để học HSK hiệu quả hơn mỗi ngày"))),
        "end_screen_footer": str(last_session.get("end_screen_footer", defaults.get("default_end_screen_footer", "meothihsk.vn"))),
        "qr_path": str(last_session.get("qr_path", "") or ""),
    }
    if session_payload["target_value"]:
        try:
            qr_path = _build_qr_from_session(dict(session_payload))
            st.image(qr_path, caption="QR / CTA hien tai", width=180)
        except Exception as exc:
            st.warning(str(exc))
            return
    else:
        st.warning("Chua co link QR/CTA. Hay nhap link tai day hoac vao tab QR / CTA phan A.")
        return
    if media_kind == "image":
        if st.button("Xuất ảnh có QR", key=f"{state_prefix}_export_image_{source_hash}"):
            out_dir = _ensure_dir("exports", "qr_images", datetime.now().strftime("%Y%m%d"))
            out_path = out_dir / f"{_slugify(Path(source_path).stem)}_qr.png"
            try:
                _save_last_qr_session(session_payload)
                overlay_qr_on_image(
                    source_path,
                    qr_path,
                    str(out_path),
                    "custom" if position_mode in {"Tu do (X/Y)", "Pixel trực tiếp"} else position,
                    size_percent,
                    margin_percent,
                    label=None if position_mode == "Pixel trực tiếp" else (label_value if label_visible else None),
                    white_box=white_box,
                    label_color=label_color,
                    label_size_percent=int(label_size_percent),
                    label_bg_color=label_bg_color,
                    label_bg_transparent=bool(label_bg_transparent),
                    x_px=int(custom_x_px_image) if position_mode == "Pixel trực tiếp" and custom_x_px_image is not None else None,
                    y_px=int(custom_y_px_image) if position_mode == "Pixel trực tiếp" and custom_y_px_image is not None else None,
                    custom_x_percent=int(custom_x_percent),
                    custom_y_percent=int(custom_y_percent),
                )
                _log_local_request("qr_image_overlay", campaign_id, f"{source_path} | {qr_path}", output_path=str(out_path))
                st.success(f"Đã lưu tại: {out_path}")
                st.image(str(out_path), use_container_width=True)
                st.code(str(out_path))
            except Exception as exc:
                st.error(f"Lỗi chèn QR vào ảnh: {exc}")
        return

    if st.button("Xuất video có QR", key=f"{state_prefix}_export_video_{source_hash}"):
        out_dir = _ensure_dir("exports", "qr_videos", datetime.now().strftime("%Y%m%d"))
        out_path = out_dir / f"{_slugify(Path(source_path).stem)}_qr.mp4"
        try:
            _save_last_qr_session(session_payload)
            overlay_qr_on_video(
                source_path,
                qr_path,
                str(out_path),
                "custom" if position_mode in {"Tu do (X/Y)", "Pixel trực tiếp"} else position,
                size_percent,
                margin_percent,
                label=None if position_mode == "Pixel trực tiếp" else (label_value if label_visible else None),
                white_box=white_box,
                label_color=label_color,
                label_size_percent=int(label_size_percent),
                label_bg_color=label_bg_color,
                label_bg_transparent=bool(label_bg_transparent),
                x_px=int(custom_x_px_image) if position_mode == "Pixel trực tiếp" and custom_x_px_image is not None else None,
                y_px=int(custom_y_px_image) if position_mode == "Pixel trực tiếp" and custom_y_px_image is not None else None,
                custom_x_percent=int(custom_x_percent),
                custom_y_percent=int(custom_y_percent),
            )
            _log_local_request("qr_video_overlay", campaign_id, f"{source_path} | {qr_path}", output_path=str(out_path))
            st.success(f"Đã lưu tại: {out_path}")
            st.video(str(out_path))
            st.code(str(out_path))
        except Exception as exc:
            st.error(f"Lỗi chèn QR vào video: {exc}")

    if allow_end_screen:
        st.markdown("#### CTA cuoi video")
        add_end_screen = st.checkbox("Them QR/CTA cuoi video", key=f"{state_prefix}_end_enable_{source_hash}")
        if not add_end_screen:
            return
        duration_seconds = st.slider(
            "Thoi luong cuoi video (giay)",
            2,
            10,
            int(last_session.get("end_screen_seconds", defaults.get("default_end_screen_seconds", 4))),
            key=f"{state_prefix}_end_duration_{source_hash}",
        )
        title = st.text_input(
            "Tieu de CTA",
            value=str(last_session.get("end_screen_title", defaults.get("default_end_screen_title", "Tải app Mẹo Thi HSK"))),
            key=f"{state_prefix}_end_title_{source_hash}",
        )
        subtitle = st.text_input(
            "Dong noi dung phu",
            value=str(last_session.get("end_screen_subtitle", defaults.get("default_end_screen_subtitle", "Quét mã QR để học HSK hiệu quả hơn mỗi ngày"))),
            key=f"{state_prefix}_end_subtitle_{source_hash}",
        )
        footer = st.text_input(
            "Footer / link / so dien thoai",
            value=str(last_session.get("end_screen_footer", defaults.get("default_end_screen_footer", "meothihsk.vn"))),
            key=f"{state_prefix}_end_footer_{source_hash}",
        )
        theme = st.selectbox("Nen", QR_THEMES, index=QR_THEMES.index("Nền tối"), key=f"{state_prefix}_end_theme_{source_hash}")
        if st.button("Thêm màn hình QR cuối video", key=f"{state_prefix}_end_export_{source_hash}"):
            out_dir = _ensure_dir("exports", "qr_videos", datetime.now().strftime("%Y%m%d"))
            out_path = out_dir / f"{_slugify(Path(source_path).stem)}_qr_end.mp4"
            try:
                session_payload["end_screen_seconds"] = int(duration_seconds)
                session_payload["end_screen_title"] = title
                session_payload["end_screen_subtitle"] = subtitle
                session_payload["end_screen_footer"] = footer
                _save_last_qr_session(session_payload)
                append_qr_end_screen(source_path, qr_path, str(out_path), duration_seconds, title, subtitle, footer, theme)
                _log_local_request("qr_end_screen", campaign_id, f"{title} | {subtitle} | {footer}", output_path=str(out_path))
                st.success(f"Đã lưu tại: {out_path}")
                st.video(str(out_path))
                st.code(str(out_path))
            except Exception as exc:
                st.error(f"Lỗi tạo màn hình QR cuối video: {exc}")
