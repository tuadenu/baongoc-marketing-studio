from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from .characters import list_characters, PRESET_CHARACTERS
from .database import list_campaigns, log_request, log_usage_cost, update_request_status
from .i18n import t
from .qr_tools import apply_qr_cta_pipeline, render_pre_generate_qr_controls
from .subtitle_tools import ffmpeg_available
from .utils import root_path
from .vertex_client import VertexClient


SCENE_SECONDS = 8
DEFAULT_STYLE = (
    "premium educational advertisement, cinematic lighting, clean modern composition, "
    "vertical mobile video, professional, no watermark, no random text"
)


@dataclass
class StoryScene:
    scene_number: int
    duration_seconds: int
    title: str
    visual_prompt: str
    narration_vi: str
    subtitle_vi: str


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
    return slug.strip("-")[:60] or "long_video"


def _ensure_output_dir(topic: str) -> Path:
    out = root_path("outputs", "long_videos", datetime.now().strftime("%Y%m%d"), _slugify(topic))
    out.mkdir(parents=True, exist_ok=True)
    return out


def _open_folder(path: str) -> None:
    try:
        subprocess.run(["open", str(Path(path).parent)], check=False)
    except Exception:
        pass


def _make_concat_list(video_paths: list[str], list_path: Path) -> None:
    lines = [f"file '{Path(path).as_posix()}'" for path in video_paths]
    list_path.write_text("\n".join(lines), encoding="utf-8")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _wrap_text(text: str, max_chars: int = 34) -> list[str]:
    words = text.strip().split()
    if not words:
        return ["Mẹo Thi HSK"]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= max_chars:
            current += " " + word
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _build_srt(scenes: list[StoryScene], intro_seconds: float = 0.0) -> str:
    blocks = []
    start = intro_seconds
    idx = 1
    for scene in scenes:
        end = start + scene.duration_seconds
        blocks.append(f"{idx}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{scene.subtitle_vi}\n")
        start = end
        idx += 1
    return "\n".join(blocks)


def _scene_prompt(character_prompt: str | None, scene: StoryScene, aspect_ratio: str) -> str:
    parts = []
    if character_prompt:
        parts.append(character_prompt.strip())
    parts.append(scene.visual_prompt.strip())
    parts.append(DEFAULT_STYLE)
    if aspect_ratio == "9:16":
        parts.append("vertical 9:16 TikTok/Reels/Shorts video")
    return ", ".join([part for part in parts if part])


def _base_character_prompt(character_mode: str, selected_preset: str | None, selected_library_character: dict | None) -> str | None:
    if character_mode == "Không dùng nhân vật":
        return None
    if character_mode == "Cô giáo Linh Nhi":
        return next((item["base_prompt"] for item in PRESET_CHARACTERS if item["name"] == "Cô giáo Linh Nhi"), None)
    if character_mode == "Nam học viên Việt Nam":
        return next((item["base_prompt"] for item in PRESET_CHARACTERS if item["name"] == "Nam học viên Việt Nam"), None)
    if selected_library_character:
        return selected_library_character.get("base_prompt")
    return None


def _storyboard_from_single_prompt(topic: str, scenes_count: int, character_name: str | None) -> list[StoryScene]:
    topic = topic.strip()
    base_topic = topic if topic else "Mẹo Thi HSK"
    scenes: list[StoryScene] = []
    for idx in range(1, scenes_count + 1):
        if idx == 1:
            title = "Hook / Mở đầu"
            visual = f"Open with a strong hook about {base_topic}, showing the main character in a modern HSK classroom, immediate attention grabbing scene"
            narration = f"Giới thiệu nhanh {base_topic}, tạo ấn tượng mạnh ngay từ vài giây đầu."
            subtitle = narration
        elif idx == scenes_count:
            title = "CTA / Kêu gọi hành động"
            visual = f"Call to action for {base_topic}, show app screen, clear promotional ending, inviting viewers to download the app"
            narration = "Kêu gọi người xem tải app Mẹo Thi HSK và bắt đầu học ngay."
            subtitle = narration
        else:
            title = f"Nội dung chính {idx}"
            visual = f"Develop the core idea of {base_topic}, practical learning benefit, educational app use case, polished marketing visual"
            narration = f"Trình bày lợi ích chính của {base_topic} ở cảnh {idx}."
            subtitle = narration
        scenes.append(
            StoryScene(
                scene_number=idx,
                duration_seconds=SCENE_SECONDS,
                title=title,
                visual_prompt=visual,
                narration_vi=narration,
                subtitle_vi=subtitle,
            )
        )
    return scenes


def _storyboard_from_multiline(prompts: list[str], target_scenes: int, topic: str) -> list[StoryScene]:
    lines = [line.strip() for line in prompts if line.strip()]
    scenes: list[StoryScene] = []
    use_count = max(target_scenes, len(lines))
    for idx in range(1, use_count + 1):
        if idx <= len(lines):
            visual = lines[idx - 1]
            title = f"Cảnh {idx}"
            narration = visual
            subtitle = visual
        elif idx == use_count:
            title = "CTA / Kêu gọi hành động"
            visual = f"Call to action for {topic}, app screen, clear end card, premium marketing ending"
            narration = "Kêu gọi tải app Mẹo Thi HSK."
            subtitle = narration
        else:
            title = f"Nội dung chính {idx}"
            visual = f"Continue the learning flow for {topic}, keep the same character and educational style"
            narration = visual
            subtitle = visual
        scenes.append(
            StoryScene(
                scene_number=idx,
                duration_seconds=SCENE_SECONDS,
                title=title,
                visual_prompt=visual,
                narration_vi=narration,
                subtitle_vi=subtitle,
            )
        )
    return scenes


def build_storyboard(
    topic: str,
    input_mode: str,
    custom_prompts_text: str,
    target_duration: int,
    character_mode: str,
    aspect_ratio: str,
    selected_library_character: dict | None,
) -> dict[str, Any]:
    target_scenes = max(1, math.ceil(target_duration / SCENE_SECONDS))
    if input_mode == "Nhiều prompt, mỗi dòng là một cảnh":
        prompts = custom_prompts_text.splitlines()
        scenes = _storyboard_from_multiline(prompts, target_scenes, topic)
    else:
        scenes = _storyboard_from_single_prompt(topic, target_scenes, character_mode)

    character_prompt = _base_character_prompt(character_mode, None, selected_library_character)
    story = {
        "topic": topic,
        "input_mode": input_mode,
        "target_duration_seconds": target_duration,
        "target_scenes": target_scenes,
        "actual_scenes": len(scenes),
        "character_mode": character_mode,
        "aspect_ratio": aspect_ratio,
        "character_prompt": character_prompt,
        "scenes": [asdict(scene) for scene in scenes],
        "created_at": datetime.now().isoformat(),
    }
    return story


def _build_campaign_slug(topic: str) -> str:
    return _slugify(topic)


def _scene_output_dir(topic: str) -> Path:
    out = _ensure_output_dir(topic)
    return out


def _write_storyboard_files(output_dir: Path, storyboard: dict[str, Any]) -> None:
    (output_dir / "storyboard.json").write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
    for scene in storyboard["scenes"]:
        scene_no = int(scene["scene_number"])
        prompt_path = output_dir / f"scene_{scene_no:02d}_prompt.txt"
        prompt_path.write_text(scene["visual_prompt"], encoding="utf-8")


def _write_srt_file(output_dir: Path, scenes: list[StoryScene], intro_seconds: float = 0.0) -> Path:
    srt_path = output_dir / "final_subtitles.srt"
    srt_path.write_text(_build_srt(scenes, intro_seconds=intro_seconds), encoding="utf-8")
    return srt_path


def _concat_videos(video_paths: list[str], output_path: str) -> str:
    list_file = Path(output_path).with_suffix(".concat.txt")
    _make_concat_list(video_paths, list_file)
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", output_path])
    return output_path


def _make_solid_clip(text: str, size: str, duration: float, output_path: Path) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={size}:d={duration}",
            "-vf",
            f"drawtext=text='{text}':fontcolor=white:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v",
            "libx264",
            "-t",
            str(duration),
            str(output_path),
        ]
    )


def _apply_intro_outro(input_path: str, preset_size: str, intro_on: bool, intro_text: str, intro_duration: float, outro_on: bool, outro_text: str, outro_duration: float, out_dir: Path) -> str:
    current_input = Path(input_path)
    ts = datetime.now().strftime("%H%M%S")
    if intro_on:
        intro_clip = out_dir / f"intro_{ts}.mp4"
        _make_solid_clip(intro_text, preset_size, intro_duration, intro_clip)
        joined = out_dir / f"join_intro_{ts}.txt"
        _make_concat_list([str(intro_clip), str(current_input)], joined)
        with_intro = out_dir / f"with_intro_{ts}.mp4"
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(joined), "-c", "copy", str(with_intro)])
        current_input = with_intro
    if outro_on:
        outro_clip = out_dir / f"outro_{ts}.mp4"
        _make_solid_clip(outro_text, preset_size, outro_duration, outro_clip)
        joined = out_dir / f"join_outro_{ts}.txt"
        _make_concat_list([str(current_input), str(outro_clip)], joined)
        final_with_outro = out_dir / f"with_outro_{ts}.mp4"
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(joined), "-c", "copy", str(final_with_outro)])
        current_input = final_with_outro
    return str(current_input)


def render_long_video_tab(default_campaign_id: int, config: dict) -> None:
    st.subheader("🎬 Tạo video dài")
    if not ffmpeg_available():
        st.warning("Chưa tìm thấy ffmpeg. Hãy cài bằng: brew install ffmpeg")

    last_output_path = st.session_state.get("last_long_video_output_path")
    if last_output_path and Path(last_output_path).exists():
        st.caption("Video dài gần nhất")
        st.video(last_output_path)
        st.code(last_output_path)
        if st.button("Mở thư mục output", key="open_last_long_video_folder"):
            _open_folder(last_output_path)

    topic = st.text_area(
        "Nhập chủ đề / prompt tổng",
        value="Giới thiệu app Mẹo Thi HSK giúp học viên Việt Nam luyện thi HSK hiệu quả.",
        height=120,
    )
    input_mode = st.radio("Kiểu nhập", ["Một prompt tổng", "Nhiều prompt, mỗi dòng là một cảnh"], horizontal=True)
    character_mode = st.selectbox(
        "Chọn nhân vật",
        ["Không dùng nhân vật", "Cô giáo Linh Nhi", "Nam học viên Việt Nam", "Từ Character Library"],
    )
    selected_library_character = None
    if character_mode == "Từ Character Library":
        library_chars = list_characters()
        if library_chars:
            char_name = st.selectbox("Nhân vật trong thư viện", [row["name"] for row in library_chars])
            selected_library_character = next((row for row in library_chars if row["name"] == char_name), None)
        else:
            st.info("Chưa có nhân vật nào trong Character Library.")

    target_duration_label = st.selectbox("Thời lượng mục tiêu", ["30 giây", "60 giây", "90 giây", "120 giây", "Tùy chỉnh"])
    if target_duration_label == "Tùy chỉnh":
        target_duration = st.number_input("Nhập thời lượng tùy chỉnh (giây)", min_value=8, max_value=600, value=30, step=8)
    else:
        target_duration = {"30 giây": 30, "60 giây": 60, "90 giây": 90, "120 giây": 120}[target_duration_label]
    aspect_ratio = st.selectbox("Tỷ lệ", ["9:16", "16:9", "1:1"], index=0)
    model_label = st.selectbox("Model", ["Veo 3.1 Lite", "Veo 3.1"])
    generate_audio = st.checkbox("Tạo âm thanh bằng Veo", value=True)
    auto_srt = st.checkbox("Tự tạo phụ đề SRT", value=True)
    auto_concat = st.checkbox("Ghép video sau khi tạo xong", value=True)
    intro_outro = st.checkbox("Thêm intro/outro", value=False)
    confirm_credit = st.checkbox("Tôi xác nhận sử dụng credit Google Cloud", value=False)
    multi_prompt_text = ""
    if input_mode == "Nhiều prompt, mỗi dòng là một cảnh":
        multi_prompt_text = st.text_area(
            "Mỗi dòng là một cảnh",
            value="Cảnh mở đầu giới thiệu app\nCảnh luyện từ vựng HSK\nCảnh luyện thi và mẹo làm bài\nCảnh kết thúc kêu gọi tải app",
            height=160,
        )

    required_scenes = max(1, math.ceil(int(target_duration) / SCENE_SECONDS))
    estimated_scenes = required_scenes
    if input_mode == "Nhiều prompt, mỗi dòng là một cảnh":
        line_count = len([line for line in multi_prompt_text.splitlines() if line.strip()])
        estimated_scenes = max(required_scenes, line_count)

    model_key = "video_lite" if model_label == "Veo 3.1 Lite" else "video_standard"
    video_model = config["vertex"]["models"].get(model_key)
    cost_per_scene_usd = float(config.get("cost_estimates", {}).get("video_lite_8s_usd" if model_label == "Veo 3.1 Lite" else "video_standard_8s_usd", 1.2 if model_label == "Veo 3.1 Lite" else 3.0))
    total_estimated_usd = cost_per_scene_usd * estimated_scenes
    total_estimated_vnd = total_estimated_usd * float(config.get("billing", {}).get("usd_to_vnd", config["cost_guard"].get("usd_to_vnd", 25000)))
    st.warning(
        f"Số cảnh dự kiến: {estimated_scenes} | Chi phí mỗi cảnh: ${cost_per_scene_usd:.2f} USD | Tổng ước tính: ${total_estimated_usd:.2f} USD / {total_estimated_vnd:,.0f} VND"
    )
    if estimated_scenes > 10:
        st.warning("Video dài có hơn 10 cảnh. Chi phí và thời gian xử lý sẽ tăng đáng kể.")
    qr_options = render_pre_generate_qr_controls(
        config=config,
        state_prefix="long_video_generate",
        media_kind="video",
        allow_end_screen=True,
    )

    if st.button("Tạo storyboard", key="create_long_storyboard_btn"):
        storyboard = build_storyboard(
            topic=topic,
            input_mode=input_mode,
            custom_prompts_text=multi_prompt_text,
            target_duration=int(target_duration),
            character_mode=character_mode,
            aspect_ratio=aspect_ratio,
            selected_library_character=selected_library_character,
        )
        st.session_state["long_video_storyboard"] = storyboard
        st.success("Đã tạo storyboard")

    storyboard = st.session_state.get("long_video_storyboard")
    if storyboard:
        st.markdown("### Storyboard")
        st.dataframe(storyboard["scenes"], use_container_width=True)

    create_clicked = st.button("Tạo video dài", key="create_long_video_btn")
    if not create_clicked:
        return

    if not confirm_credit:
        st.warning("Vui lòng tick xác nhận credit trước khi tạo.")
        return

    if not video_model:
        st.error("Chưa cấu hình model Veo trong config.yaml.")
        return

    storyboard = storyboard or build_storyboard(
        topic=topic,
        input_mode=input_mode,
        custom_prompts_text=multi_prompt_text,
        target_duration=int(target_duration),
        character_mode=character_mode,
        aspect_ratio=aspect_ratio,
        selected_library_character=selected_library_character,
    )
    st.session_state["long_video_storyboard"] = storyboard

    campaign_name = next(
        (row["campaign_name"] for row in list_campaigns() if int(row["id"]) == int(default_campaign_id)),
        topic,
    )
    output_dir = _ensure_output_dir(campaign_name)
    _write_storyboard_files(output_dir, storyboard)
    scenes = [StoryScene(**scene) for scene in storyboard["scenes"]]
    character_prompt = storyboard.get("character_prompt")
    total_scenes = len(scenes)
    progress = st.progress(0, text="Đang tạo storyboard")
    status_box = st.empty()
    scene_outputs: list[str] = []
    prompt_base = topic.strip()
    campaign_id = default_campaign_id
    project_id = st.session_state.get("project_id")
    billed_vnd = 0.0
    try:
        client = VertexClient(
            project_id=project_id,
            region=st.session_state.get("region"),
            imagen_model=config["vertex"]["models"].get("image_standard", ""),
            veo_model=video_model,
            api_key=st.session_state.get("api_key"),
        )
        for idx, scene in enumerate(scenes, start=1):
            progress.progress(int((idx - 1) / max(total_scenes, 1) * 100), text=f"Đang tạo cảnh {idx}/{total_scenes}")
            status_box.info(f"Đang tạo cảnh {idx}/{total_scenes}")
            scene_dir = output_dir / f"scene_{idx:02d}"
            scene_dir.mkdir(parents=True, exist_ok=True)
            scene_prompt = _scene_prompt(character_prompt, scene, aspect_ratio)
            (output_dir / f"scene_{idx:02d}_prompt.txt").write_text(scene_prompt, encoding="utf-8")
            request_id = log_request(
                "long_video_scene",
                campaign_id,
                f"scene {idx} / {total_scenes}",
                model=model_label,
                prompt=scene_prompt,
                status="generating",
            )
            estimated_cost_usd = cost_per_scene_usd
            estimated_cost_vnd = estimated_cost_usd * float(config.get("billing", {}).get("usd_to_vnd", config["cost_guard"].get("usd_to_vnd", 25000)))
            log_usage_cost(
                request_id=request_id,
                project_id=project_id,
                model=model_label,
                media_type="long_video_scene",
                estimated_cost_usd=estimated_cost_usd,
                estimated_cost_vnd=estimated_cost_vnd,
            )
            try:
                output_path = client.generate_video(
                    prompt=scene_prompt,
                    model=video_model,
                    aspect_ratio=aspect_ratio,
                    duration_seconds=SCENE_SECONDS,
                    output_dir=str(scene_dir),
                    generate_audio=generate_audio,
                )
                scene_final_path = output_dir / f"scene_{idx:02d}.mp4"
                shutil.copy2(output_path, scene_final_path)
                scene_outputs.append(str(scene_final_path))
                billed_vnd += estimated_cost_vnd
                update_request_status(request_id, "completed", output_path=str(scene_final_path))
                st.caption(f"Cảnh {idx}/{total_scenes} xong: {scene_final_path}")
                st.video(str(scene_final_path))
            except Exception as scene_exc:
                update_request_status(request_id, "failed", detail=str(scene_exc))
                raise

        progress.progress(75, text="Đang ghép video")
        final_video = output_dir / "final_long_video.mp4"
        if auto_concat and len(scene_outputs) > 1:
            try:
                _concat_videos(scene_outputs, str(final_video))
            except Exception as exc:
                st.error(f"Lỗi khi ghép video: {exc}")
                st.caption("Các scene mp4 vẫn được giữ nguyên trong thư mục output.")
                shutil.copy2(scene_outputs[-1], final_video)
        else:
            shutil.copy2(scene_outputs[-1], final_video)

        intro_seconds = 0.0
        rendered_output = final_video
        if intro_outro:
            rendered_output = Path(
                _apply_intro_outro(
                    str(final_video),
                    preset_size="1080x1920" if aspect_ratio == "9:16" else "1920x1080" if aspect_ratio == "16:9" else "1080x1080",
                    intro_on=True,
                    intro_text="Mẹo Thi HSK",
                    intro_duration=1.5,
                    outro_on=True,
                    outro_text="Tải app Mẹo Thi HSK",
                    outro_duration=1.5,
                    out_dir=output_dir,
                )
            )
            intro_seconds = 1.5
            if rendered_output != final_video:
                shutil.copy2(rendered_output, final_video)
        final_output_path = final_video
        final_output_path = Path(
            apply_qr_cta_pipeline(
                source_path=str(final_output_path),
                config=config,
                campaign_id=campaign_id,
                options=qr_options,
            )
        )

        srt_path = None
        if auto_srt:
            srt_path = _write_srt_file(output_dir, scenes, intro_seconds=intro_seconds)

        final_request_id = log_request(
            "long_video_final",
            campaign_id,
            prompt_base,
            model=model_label,
            prompt=prompt_base,
            status="completed",
            output_path=str(final_output_path),
        )
        update_request_status(final_request_id, "completed", output_path=str(final_output_path))
        progress.progress(100, text="Hoàn thành")
        status_box.success("Hoàn thành")
        st.success("Hoàn thành")
        st.caption(f"Đã lưu tại: {final_output_path}")
        st.video(str(final_output_path))
        st.code(str(final_output_path))
        if st.button("Mở thư mục output", key="open_long_video_folder_result"):
            _open_folder(str(final_output_path))
        if srt_path:
            st.caption(f"Đã lưu phụ đề: {srt_path}")
            st.code(str(srt_path))
        st.session_state["last_long_video_output_path"] = str(final_output_path)
    except Exception as exc:
        progress.progress(100, text="Thất bại")
        status_box.error(str(exc))
        st.error(f"Lỗi: {exc}")
