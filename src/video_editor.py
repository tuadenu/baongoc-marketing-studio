from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import streamlit as st

from .i18n import t
from .utils import root_path


PRESET_EXPORTS = {
    "TikTok/Reels/Shorts": {"size": "1080x1920", "aspect": "9:16", "subtitle_pos": "bottom"},
    "YouTube": {"size": "1920x1080", "aspect": "16:9", "subtitle_pos": "bottom"},
    "Facebook Post": {"size": "1080x1080", "aspect": "1:1", "subtitle_pos": "bottom"},
}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _ensure_export_dir() -> Path:
    out = root_path("exports", "final", datetime.now().strftime("%Y%m%d"))
    out.mkdir(parents=True, exist_ok=True)
    return out


def _probe_duration(path: str) -> str:
    if not shutil.which("ffprobe"):
        return "Không đọc được"
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        value = float((result.stdout or "").strip())
        return f"{value:.1f}s"
    except Exception:
        return "Không đọc được"


def _collect_video_files() -> list[str]:
    roots = [root_path("outputs", "videos"), root_path("outputs", "videos", "test"), root_path("outputs", "videos", "image_to_video")]
    files = []
    for root in roots:
        if root.exists():
            files.extend([str(p) for p in root.rglob("*.mp4")])
    return sorted(set(files))


def _make_concat_list(video_paths: list[str], list_path: Path) -> None:
    lines = [f"file '{Path(path).as_posix()}'" for path in video_paths]
    list_path.write_text("\n".join(lines), encoding="utf-8")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _scale_crop_filter(preset: str, mode: str) -> str:
    size = PRESET_EXPORTS[preset]["size"]
    w, h = size.split("x")
    if mode == "Crop center":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    if mode == "Blur background":
        return (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20[bg];"
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
    return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"


def _write_text_overlay_srt(text: str, path: Path, duration: float) -> None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        lines = ["Mẹo Thi HSK"]
    chunk_count = len(lines)
    seg = duration / max(chunk_count, 1)
    blocks = []
    for idx, line in enumerate(lines, start=1):
        start = idx - 1 * seg
        end = idx * seg
        blocks.append(f"{idx}\n00:00:{start:06.3f} --> 00:00:{end:06.3f}\n{line}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def render_editor_tab() -> None:
    st.subheader(t("tab_editor"))
    if not ffmpeg_available():
        st.warning("Chưa tìm thấy ffmpeg. Hãy cài bằng: brew install ffmpeg")

    preset_name = st.selectbox("Preset xuất mạng xã hội", list(PRESET_EXPORTS.keys()))
    preset = PRESET_EXPORTS[preset_name]
    resize_mode = st.selectbox("Cách xử lý tỷ lệ", ["Crop center", "Blur background", "Fit with black bars"])

    uploaded = st.file_uploader("Upload video local", accept_multiple_files=True, type=["mp4", "mov", "m4v"])
    selected = st.multiselect("Chọn video", _collect_video_files())

    if "editor_queue" not in st.session_state:
        st.session_state["editor_queue"] = []
    queue = list(st.session_state["editor_queue"])

    add_cols = st.columns([2, 1])
    with add_cols[0]:
        if uploaded:
            for item in uploaded:
                temp_dir = root_path("data", "uploads")
                temp_dir.mkdir(parents=True, exist_ok=True)
                dest = temp_dir / item.name
                dest.write_bytes(item.read())
                if str(dest) not in queue:
                    queue.append(str(dest))
    with add_cols[1]:
        if st.button("Thêm video đã chọn"):
            for path in selected:
                if path not in queue:
                    queue.append(path)
    st.session_state["editor_queue"] = queue

    st.markdown("### Danh sách video đã chọn")
    if not queue:
        st.info("Chưa có video nào.")
    else:
        for idx, path in enumerate(list(queue), start=1):
            cols = st.columns([0.1, 0.7, 0.15, 0.05])
            with cols[0]:
                st.write(idx)
            with cols[1]:
                st.write(Path(path).name)
                st.caption(_probe_duration(path))
            with cols[2]:
                if st.button("Xóa", key=f"remove_video_{idx}"):
                    queue.remove(path)
                    st.session_state["editor_queue"] = queue
                    st.rerun()
            with cols[3]:
                st.write(" ")

    intro_on = st.checkbox("Bật intro", value=True)
    outro_on = st.checkbox("Bật outro", value=True)
    intro_text = st.text_input("Intro text", value="Mẹo Thi HSK")
    outro_text = st.text_input("Outro text", value="Tải app Mẹo Thi HSK")
    intro_duration = st.number_input("Thời lượng intro", min_value=0.5, max_value=5.0, value=1.5, step=0.5)
    outro_duration = st.number_input("Thời lượng outro", min_value=0.5, max_value=5.0, value=1.5, step=0.5)

    export_base = st.text_input("Tên file xuất", value="final_video")
    if st.button("Xuất video"):
        if not queue:
            st.error("Chưa có video để ghép.")
            return
        if not ffmpeg_available():
            st.error("Chưa có ffmpeg. Hãy cài bằng: brew install ffmpeg")
            return

        export_dir = _ensure_export_dir()
        ts = datetime.now().strftime("%H%M%S")
        output_path = export_dir / f"{export_base}_{ts}.mp4"
        concat_input = export_dir / f"concat_{ts}.txt"
        temp_output = export_dir / f"temp_{ts}.mp4"
        _make_concat_list(queue, concat_input)

        status = st.empty()
        status.info("Đang ghép video")
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_input), "-c", "copy", str(temp_output)])

        current_input = temp_output
        if intro_on or outro_on:
            status.info("Đang chèn intro/outro")
            with_intro = export_dir / f"with_intro_{ts}.mp4"
            filters = []
            inputs = [str(current_input)]
            if intro_on:
                inputs.insert(0, str(current_input))
            if outro_on:
                inputs.append(str(current_input))
            # pragmatic, simple intro/outro via color + text if enabled
            if intro_on:
                intro_clip = export_dir / f"intro_{ts}.mp4"
                _run([
                    "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={preset['size']}:d={intro_duration}",
                    "-vf", f"drawtext=text='{intro_text}':fontcolor=white:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2",
                    "-c:v", "libx264", "-t", str(intro_duration), str(intro_clip)
                ])
                joined = export_dir / f"join_intro_{ts}.txt"
                _make_concat_list([str(intro_clip), str(current_input)], joined)
                _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(joined), "-c", "copy", str(with_intro)])
                current_input = with_intro
            if outro_on:
                outro_clip = export_dir / f"outro_{ts}.mp4"
                _run([
                    "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={preset['size']}:d={outro_duration}",
                    "-vf", f"drawtext=text='{outro_text}':fontcolor=white:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2",
                    "-c:v", "libx264", "-t", str(outro_duration), str(outro_clip)
                ])
                joined = export_dir / f"join_outro_{ts}.txt"
                _make_concat_list([str(current_input), str(outro_clip)], joined)
                _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(joined), "-c", "copy", str(output_path)])
            else:
                shutil.copy2(current_input, output_path)
        else:
            shutil.copy2(current_input, output_path)

        status.success("Hoàn thành")
        st.success(f"{t('saved_to')}: {output_path}")
        st.video(str(output_path))
        if st.button("Mở thư mục export"):
            subprocess.run(["open", str(output_path.parent)], check=False)
