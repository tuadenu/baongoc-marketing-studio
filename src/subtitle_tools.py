from __future__ import annotations

import math
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import streamlit as st

from .i18n import t
from .utils import root_path


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _ensure_export_dir() -> Path:
    out = root_path("exports", "final", datetime.now().strftime("%Y%m%d"))
    out.mkdir(parents=True, exist_ok=True)
    return out


def wrap_subtitle_text(text: str, max_chars: int = 34) -> list[str]:
    parts = re.split(r"(?<=[\.\,\!\?\:])\s+|\n+", text.strip())
    lines: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            lines.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            lines.append(part)
    return lines


def build_srt_from_text(text: str, video_duration: float) -> str:
    lines = wrap_subtitle_text(text)
    if not lines:
        lines = ["Mẹo Thi HSK"]
    seg = video_duration / len(lines)
    blocks = []
    for idx, line in enumerate(lines, start=1):
        start = (idx - 1) * seg
        end = idx * seg
        blocks.append(f"{idx}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{line}\n")
    return "\n".join(blocks)


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def burn_subtitles(video_path: str, srt_path: str, output_path: str, font_size: int = 44, style: str = "Nền đen mờ") -> str:
    if not ffmpeg_available():
        raise RuntimeError("Chưa có ffmpeg. Hãy cài bằng: brew install ffmpeg")
    if style == "Nền đen mờ":
        force_style = f"Fontsize={font_size},PrimaryColour=&HFFFFFF&,BackColour=&H80000000&,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV=40"
    else:
        force_style = f"Fontsize={font_size},PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=40"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vf",
            f"subtitles={srt_path}:force_style='{force_style}'",
            "-c:a",
            "copy",
            output_path,
        ],
        check=True,
    )
    return output_path


def render_subtitle_tab() -> None:
    st.subheader(t("tab_subtitles"))
    if not ffmpeg_available():
        st.warning("Chưa tìm thấy ffmpeg. Hãy cài bằng: brew install ffmpeg")

    subtitle_text = st.text_area("Subtitle text", value="Xin chào, hôm nay học HSK cùng Linh Nhi. App Mẹo Thi HSK rất tiện cho việc luyện thi.")
    video_file = st.file_uploader("Upload video", type=["mp4", "mov", "m4v"])
    srt_file = st.file_uploader("Upload file SRT", type=["srt"])
    font_size = st.slider("Font size", min_value=24, max_value=72, value=44, step=2)
    subtitle_style = st.selectbox("Style phụ đề", ["Nền đen mờ", "Viền chữ"])
    video_format = st.selectbox("Preset xuất", ["TikTok/Reels/Shorts", "YouTube", "Facebook Post"])

    if "generated_srt" not in st.session_state:
        st.session_state["generated_srt"] = None

    if st.button("Tạo SRT"):
        if not video_file:
            st.error("Hãy upload video để ước tính thời lượng.")
        else:
            temp_dir = root_path("data", "uploads")
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_video = temp_dir / video_file.name
            temp_video.write_bytes(video_file.read())
            # best effort: 8s default if duration unavailable
            duration = 8.0
            srt_text = build_srt_from_text(subtitle_text, duration)
            out = _ensure_export_dir() / f"subtitle_{datetime.now().strftime('%H%M%S')}.srt"
            out.write_text(srt_text, encoding="utf-8")
            st.session_state["generated_srt"] = str(out)
            st.success(f"Đã lưu tại: {out}")
            st.code(srt_text)

    srt_path = None
    if srt_file:
        temp_dir = root_path("data", "uploads")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_srt = temp_dir / srt_file.name
        temp_srt.write_bytes(srt_file.read())
        srt_path = str(temp_srt)
    elif st.session_state.get("generated_srt"):
        srt_path = st.session_state["generated_srt"]

    if st.button("Burn subtitles") and video_file and srt_path:
        temp_dir = root_path("data", "uploads")
        temp_dir.mkdir(parents=True, exist_ok=True)
        video_path = temp_dir / video_file.name
        if not video_path.exists():
            video_path.write_bytes(video_file.read())
        export_dir = _ensure_export_dir()
        output_path = export_dir / f"burn_subtitle_{datetime.now().strftime('%H%M%S')}.mp4"
        try:
            burn_subtitles(str(video_path), srt_path, str(output_path), font_size=font_size, style=subtitle_style)
            st.success(f"Đã lưu tại: {output_path}")
            st.video(str(output_path))
        except Exception as exc:
            st.error(f"Lỗi: {exc}")
    if st.session_state.get("generated_srt"):
        st.caption(f"{t('saved_to')}: {st.session_state['generated_srt']}")
