from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import streamlit as st

from .database import get_ui_state, log_request, log_usage_cost, save_prompt, save_ui_state, update_prompt_status, update_request_status
from .i18n import t
from .prompt_presets import PRESETS
from .utils import root_path
from .vertex_client import VertexClient


VIDEO_COSTS_USD = {
    "Veo 3.1 Lite": {8: 0.20, 16: 0.35},
    "Veo 3.1": {8: 0.50, 16: 0.90},
}


def _estimate_video_cost_usd(config: dict, model_label: str, duration: int) -> float:
    key = "video_lite_8s_usd" if model_label == "Veo 3.1 Lite" else "video_standard_8s_usd"
    base = float(config.get("cost_estimates", {}).get(key, VIDEO_COSTS_USD[model_label][duration if duration in VIDEO_COSTS_USD[model_label] else 8]))
    if duration == 16:
        return base * 2
    return base


def _video_output_dir(campaign_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d")
    out_dir = root_path("outputs", "videos", stamp, campaign_name.replace(" ", "_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _open_folder(path: str) -> None:
    try:
        subprocess.run(["open", str(Path(path).parent)], check=False)
    except Exception:
        pass


def _save_uploaded_image(uploaded_file) -> str:
    target_dir = root_path("data", "uploads")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / uploaded_file.name
    target.write_bytes(uploaded_file.read())
    return str(target)


def _make_freeze_clip(image_path: str, aspect_ratio: str, duration: int, output_path: str) -> str:
    size_map = {"16:9": "1920x1080", "9:16": "1080x1920", "1:1": "1080x1080"}
    size = size_map.get(aspect_ratio, "1080x1920")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            image_path,
            "-t",
            str(duration),
            "-vf",
            f"scale={size.split('x')[0]}:{size.split('x')[1]}:force_original_aspect_ratio=decrease,pad={size.split('x')[0]}:{size.split('x')[1]}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            output_path,
        ],
        check=True,
    )
    return output_path


def _trim_video(input_path: str, duration: int, output_path: str) -> str:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-t",
            str(duration),
            "-c",
            "copy",
            output_path,
        ],
        check=True,
    )
    return output_path


def _concat_videos(video_paths: list[str], output_path: str) -> str:
    list_file = Path(output_path).with_suffix(".concat.txt")
    list_file.write_text("\n".join([f"file '{Path(p).as_posix()}'" for p in video_paths]), encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            output_path,
        ],
        check=True,
    )
    return output_path


def render_video_tab(default_campaign_id: int, config: dict) -> None:
    st.subheader(t("video_generator"))
    last_prompt = get_ui_state("video_prompt", PRESETS["TikTok Hook"]) or PRESETS["TikTok Hook"]
    last_model = get_ui_state("video_model_label", "Veo 3.1 Lite") or "Veo 3.1 Lite"
    last_duration = int(get_ui_state("video_duration", "8") or 8)
    last_aspect = get_ui_state("video_aspect_ratio", "9:16") or "9:16"
    last_generate_audio = (get_ui_state("video_generate_audio", "true") or "true").lower() == "true"
    last_use_reference = (get_ui_state("video_use_reference_image", "false") or "false").lower() == "true"
    with st.form("video_form"):
        prompt = st.text_area(t("prompt"), value=last_prompt)
        model = st.selectbox(t("model"), ["Veo 3.1 Lite", "Veo 3.1"], index=["Veo 3.1 Lite", "Veo 3.1"].index(last_model) if last_model in ["Veo 3.1 Lite", "Veo 3.1"] else 0)
        duration = st.selectbox("Thời lượng video gốc", [4, 8], index=[4, 8].index(last_duration) if last_duration in [4, 8] else 1)
        aspect_ratio = st.selectbox(t("aspect_ratio"), ["16:9", "9:16", "1:1"], index=["16:9", "9:16", "1:1"].index(last_aspect) if last_aspect in ["16:9", "9:16", "1:1"] else 1)
        generate_audio = st.checkbox(t("generate_audio"), value=last_generate_audio)
        use_reference_image = st.checkbox("Dùng ảnh làm reference", value=last_use_reference)
        reference_image = st.file_uploader("Ảnh người mẫu", type=["png", "jpg", "jpeg"])
        freeze_images = st.file_uploader("Ảnh nối thêm ở đuôi video", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
        submitted = st.form_submit_button("Xem chi phí ước tính")

    if submitted:
        save_ui_state("video_prompt", prompt)
        save_ui_state("video_model_label", model)
        save_ui_state("video_duration", str(int(duration)))
        save_ui_state("video_aspect_ratio", aspect_ratio)
        save_ui_state("video_generate_audio", "true" if generate_audio else "false")
        save_ui_state("video_use_reference_image", "true" if use_reference_image else "false")
        reference_image_path = _save_uploaded_image(reference_image) if reference_image else None
        saved_freeze = [_save_uploaded_image(item) for item in freeze_images] if freeze_images else []
        if reference_image_path:
            save_ui_state("video_reference_image_path", reference_image_path)
        if freeze_images:
            save_ui_state("video_freeze_image_paths", "\n".join(saved_freeze))
        st.session_state["pending_video_request"] = {
            "campaign_id": default_campaign_id,
            "prompt": prompt,
            "model_label": model,
            "duration": int(duration),
            "aspect_ratio": aspect_ratio,
            "generate_audio": generate_audio,
            "use_reference_image": use_reference_image,
            "reference_image_path": reference_image_path,
            "model_key": "video_lite" if model == "Veo 3.1 Lite" else "video_standard",
            "freeze_image_paths": saved_freeze,
        }

    pending = st.session_state.get("pending_video_request")
    if not pending:
        return

    if pending.get("freeze_image_paths"):
        st.markdown("### Danh sách ảnh nối đuôi")
        if st.button("Xóa tất cả ảnh nối đuôi", key="clear_freeze_images"):
            pending["freeze_image_paths"] = []
            st.session_state["pending_video_request"] = pending
            for key in [
                k
                for k in list(st.session_state.keys())
                if k.startswith("freeze_seconds_") or k.startswith("freeze_order_")
            ]:
                st.session_state.pop(key, None)
            st.rerun()
        delete_index = None
        for idx, image_path in enumerate(list(pending["freeze_image_paths"]), start=1):
            cols = st.columns([0.18, 0.42, 0.18, 0.12, 0.1])
            with cols[0]:
                st.write(f"Ảnh {idx}")
            with cols[1]:
                st.caption(Path(image_path).name)
            with cols[2]:
                st.caption(f"{st.session_state.get(f'freeze_seconds_{idx}', 2)}s")
            with cols[3]:
                st.caption(f"Thứ tự: {st.session_state.get(f'freeze_order_{idx}', idx)}")
            with cols[4]:
                if st.button("Xóa", key=f"delete_freeze_{idx}"):
                    delete_index = idx - 1
        if delete_index is not None:
            removed_path = pending["freeze_image_paths"].pop(delete_index)
            st.session_state["pending_video_request"] = pending
            for key in [k for k in list(st.session_state.keys()) if k.startswith("freeze_seconds_") or k.startswith("freeze_order_")]:
                st.session_state.pop(key, None)
            st.rerun()

    usd = VIDEO_COSTS_USD[pending["model_label"]][pending["duration"]]
    vnd = usd * float(config["cost_guard"].get("usd_to_vnd", 25000))
    st.warning(f"{t('estimated_cost')}: ${usd:.2f} USD / {vnd:,.0f} VND")
    freeze_seconds = []
    freeze_order = []
    if pending.get("freeze_image_paths"):
        st.markdown("### Thời lượng cho từng ảnh")
        for idx, image_path in enumerate(pending["freeze_image_paths"], start=1):
            cols = st.columns([0.18, 0.42, 0.2, 0.2])
            with cols[0]:
                st.write(f"Ảnh {idx}")
            with cols[1]:
                st.caption(Path(image_path).name)
            with cols[2]:
                freeze_seconds.append(
                    st.slider(
                        f"Số giây ảnh {idx}",
                        min_value=1,
                        max_value=30,
                        value=2,
                        key=f"freeze_seconds_{idx}",
                    )
                )
            with cols[3]:
                freeze_order.append(
                    st.number_input(
                        f"Thứ tự ảnh {idx}",
                        min_value=1,
                        max_value=len(pending["freeze_image_paths"]),
                        value=idx,
                        step=1,
                        key=f"freeze_order_{idx}",
                    )
                )
    total_freeze_seconds = sum(int(x) for x in freeze_seconds) if freeze_seconds else 0
    projected_total = int(pending["duration"]) + total_freeze_seconds
    st.info(f"Tổng thời lượng dự kiến cuối: {projected_total}s")
    if pending.get("freeze_image_paths"):
        st.caption("Ảnh sẽ được ghép theo thứ tự bạn chọn bên phải.")
        if freeze_seconds:
            st.markdown("### Tóm tắt ảnh nối đuôi")
            ordered_preview = sorted(
                [
                    (
                        int(st.session_state.get(f"freeze_order_{idx}", idx)),
                        idx,
                        image_path,
                        int(st.session_state.get(f"freeze_seconds_{idx}", 2)),
                    )
                    for idx, image_path in enumerate(pending["freeze_image_paths"], start=1)
                ],
                key=lambda item: (item[0], item[1]),
            )
            for position, idx, image_path, seconds in ordered_preview:
                st.write(f"- Ảnh {idx}: `{Path(image_path).name}` - `{seconds}s`")
            st.write(f"**Tổng ảnh nối đuôi:** `{total_freeze_seconds}s`")
            st.write(f"**Tổng video cuối dự kiến:** `{projected_total}s`")
    confirm = st.checkbox(t("confirm_video"), key="confirm_video_generate")
    if confirm and st.button("Tạo video", key="run_video_now"):
        progress = st.progress(0, text="Đang chuẩn bị")
        video_model = config["vertex"]["models"].get(pending["model_key"])
        if not video_model:
            st.error(t("model_not_configured"))
            return
        client = VertexClient(
            project_id=st.session_state["project_id"],
            region=st.session_state["region"],
            imagen_model=config["vertex"]["models"].get("image_standard", ""),
            veo_model=video_model,
            api_key=None,
        )
        output_dir = _video_output_dir("Chiến_dịch_mặc_định")
        prompt_id = save_prompt(
            {
                "campaign_id": pending["campaign_id"],
                "type": "video",
                "prompt": pending["prompt"],
                "negative_prompt": "",
                "model": pending["model_label"],
                "aspect_ratio": pending["aspect_ratio"],
                "status": "generating",
            }
        )
        estimated_usd = _estimate_video_cost_usd(config, pending["model_label"], pending["duration"])
        estimated_vnd = estimated_usd * float(config.get("billing", {}).get("usd_to_vnd", config["cost_guard"].get("usd_to_vnd", 25000)))
        request_id = log_request(
            "video",
            pending["campaign_id"],
            "vertex video generation",
            model=pending["model_label"],
            prompt=pending["prompt"],
            status="generating",
        )
        log_usage_cost(
            request_id=request_id,
            project_id=st.session_state["project_id"],
            model=pending["model_label"],
            media_type="video",
            estimated_cost_usd=estimated_usd,
            estimated_cost_vnd=estimated_vnd,
        )
        status_box = st.empty()
        status_box.info("Đang gửi request")
        try:
            progress.progress(15, text="Đang chờ Veo xử lý")
            status_box.info("Đang chờ Veo xử lý")
            output_path = client.generate_video(
                prompt=pending["prompt"],
                model=video_model,
                aspect_ratio=pending["aspect_ratio"],
                duration_seconds=pending["duration"],
                output_dir=str(output_dir),
                reference_image_path=pending["reference_image_path"] if pending.get("use_reference_image") else None,
            )
            if pending["duration"] == 4:
                progress.progress(50, text="Đang cắt video gốc về 4 giây")
                trimmed = output_dir / f"trim_{datetime.now().strftime('%H%M%S')}.mp4"
                _trim_video(output_path, 4, str(trimmed))
                output_path = str(trimmed)
            progress.progress(55, text="Đang tải video về máy")
            status_box.info("Đang tải video về máy")
            if pending.get("freeze_image_paths"):
                extended_parts = [output_path]
                total_freeze = sum(int(s) for s in freeze_seconds) if freeze_seconds else 0
                if total_freeze:
                    status_box.info("Đang nối ảnh ở đuôi video")
                    progress.progress(70, text="Đang nối ảnh ở đuôi video")
                ordered_items = sorted(
                    [
                        (
                            int(st.session_state.get(f"freeze_order_{idx}", idx)),
                            idx,
                            image_path,
                        )
                        for idx, image_path in enumerate(pending["freeze_image_paths"], start=1)
                    ],
                    key=lambda item: (item[0], item[1]),
                )
                for position, idx, image_path in ordered_items:
                    seconds = int(st.session_state.get(f"freeze_seconds_{idx}", 2))
                    st.caption(f"Ảnh {idx}: {seconds}s")
                    freeze_clip = output_dir / f"freeze_{idx}_{datetime.now().strftime('%H%M%S')}.mp4"
                    _make_freeze_clip(image_path, pending["aspect_ratio"], seconds, str(freeze_clip))
                    extended_parts.append(str(freeze_clip))
                if len(extended_parts) > 1:
                    final_output = output_dir / f"extended_{datetime.now().strftime('%H%M%S')}.mp4"
                    _concat_videos(extended_parts, str(final_output))
                    output_path = str(final_output)
            progress.progress(100, text="Hoàn thành")
            update_prompt_status(prompt_id, "completed", output_path)
            update_request_status(request_id, "completed", output_path=output_path)
            st.success(t("status_completed"))
            st.caption(f"{t('saved_to')}: {output_path}")
            st.video(output_path)
            st.code(output_path)
            if st.button("Mở thư mục video", key="open_video_folder"):
                _open_folder(output_path)
        except Exception as exc:
            update_prompt_status(prompt_id, "failed")
            update_request_status(request_id, "failed", detail=str(exc))
            progress.progress(100, text="Thất bại")
            st.error(f"{t('error')}: {exc}")
        st.session_state.pop("pending_video_request", None)
