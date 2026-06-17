from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from .characters import get_selected_character, list_characters
from .database import get_ui_state, log_request, log_usage_cost, save_prompt, save_ui_state, update_request_status
from .utils import root_path
from .video_generator import _concat_videos, _make_freeze_clip, _open_folder, _save_uploaded_image, _video_output_dir
from .vertex_client import VertexClient


def _build_motion_prompt(character: dict | None, motion_prompt: str) -> str:
    if character and character.get("base_prompt"):
        return f"{character['base_prompt']}\n{motion_prompt}"
    return motion_prompt


def _choose_image_source() -> str | None:
    source = st.radio(
        "Nguồn ảnh",
        ["Ảnh đã tạo", "Upload ảnh local", "Ảnh reference của nhân vật"],
        horizontal=True,
    )

    if source == "Ảnh đã tạo":
        image_root = root_path("outputs", "images")
        files = sorted(
            [p for p in image_root.rglob("*.png")]
            + [p for p in image_root.rglob("*.jpg")]
            + [p for p in image_root.rglob("*.jpeg")]
        )
        if not files:
            st.info("Chưa có ảnh nào trong outputs/images")
            return None
        return st.selectbox("Chọn ảnh đã tạo", [str(p) for p in files])

    if source == "Upload ảnh local":
        uploaded = st.file_uploader("Tải ảnh lên", type=["png", "jpg", "jpeg"])
        if not uploaded:
            return None
        target = root_path("data", "uploads")
        target.mkdir(parents=True, exist_ok=True)
        saved = target / uploaded.name
        saved.write_bytes(uploaded.read())
        return str(saved)

    characters = list_characters()
    if not characters:
        st.info("Chưa có nhân vật nào.")
        return None
    character_name = st.selectbox("Chọn nhân vật", [row["name"] for row in characters])
    chosen = next((row for row in characters if row["name"] == character_name), None)
    if chosen and chosen.get("reference_image_path"):
        st.session_state["selected_character"] = chosen
        return chosen["reference_image_path"]
    return None


def _clear_freeze_state(prefix: str) -> None:
    for key in [k for k in list(st.session_state.keys()) if k.startswith(prefix)]:
        st.session_state.pop(key, None)


def render_image_to_video_tab(config: dict, default_campaign_id: int) -> None:
    st.subheader("Tạo video từ ảnh")
    selected_character = get_selected_character()
    selected_image_path = _choose_image_source()

    if selected_image_path and Path(selected_image_path).exists():
        st.image(selected_image_path, caption=selected_image_path, use_container_width=True)
        st.caption("Ảnh đầu vào sẽ được dùng làm khung đầu tiên cho Vertex AI, rồi có thể nối thêm ảnh ở đuôi.")

    with st.form("image_to_video_form"):
        motion_prompt = st.text_area(
            "Mô tả chuyển động",
            value=get_ui_state("image_to_video_prompt", "She smiles and speaks Vietnamese to introduce the Mẹo Thi HSK app, gentle camera movement, premium educational advertisement.")
            or "She smiles and speaks Vietnamese to introduce the Mẹo Thi HSK app, gentle camera movement, premium educational advertisement.",
        )
        model_label = st.selectbox("Model", ["Veo 3.1 Lite", "Veo 3.1"], index=0 if (get_ui_state("image_to_video_model_label", "Veo 3.1 Lite") or "Veo 3.1 Lite") == "Veo 3.1 Lite" else 1)
        duration = st.selectbox("Thời lượng video gốc", [4, 8], index=[4, 8].index(int(get_ui_state("image_to_video_duration", "8") or 8)) if int(get_ui_state("image_to_video_duration", "8") or 8) in [4, 8] else 1)
        aspect_ratio = st.selectbox("Tỷ lệ khung hình", ["9:16", "16:9"], index=0 if (get_ui_state("image_to_video_aspect_ratio", "9:16") or "9:16") == "9:16" else 1)
        generate_audio = st.checkbox("Tạo âm thanh", value=(get_ui_state("image_to_video_generate_audio", "true") or "true").lower() == "true")
        freeze_images = st.file_uploader(
            "Ảnh nối thêm ở đuôi video",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
        )
        use_credit = st.checkbox("Tôi xác nhận sử dụng credit Google Cloud", value=False)
        submitted = st.form_submit_button("Xem chi phí ước tính")

    if submitted:
        save_ui_state("image_to_video_prompt", motion_prompt)
        save_ui_state("image_to_video_model_label", model_label)
        save_ui_state("image_to_video_duration", str(int(duration)))
        save_ui_state("image_to_video_aspect_ratio", aspect_ratio)
        save_ui_state("image_to_video_generate_audio", "true" if generate_audio else "false")
        st.session_state["pending_image_to_video_request"] = {
            "campaign_id": default_campaign_id,
            "prompt": motion_prompt,
            "model_label": model_label,
            "duration": int(duration),
            "aspect_ratio": aspect_ratio,
            "generate_audio": generate_audio,
            "freeze_image_paths": [_save_uploaded_image(item) for item in freeze_images] if freeze_images else [],
            "selected_image_path": selected_image_path,
            "selected_character": selected_character,
        }
        if selected_image_path:
            save_ui_state("image_to_video_selected_image_path", selected_image_path)

    pending = st.session_state.get("pending_image_to_video_request")
    if not pending:
        return

    if pending.get("freeze_image_paths"):
        st.markdown("### Danh sách ảnh nối đuôi")
        if st.button("Xóa tất cả ảnh nối đuôi", key="clear_image_to_video_freeze_images"):
            pending["freeze_image_paths"] = []
            st.session_state["pending_image_to_video_request"] = pending
            _clear_freeze_state("image_to_video_freeze_seconds_")
            _clear_freeze_state("image_to_video_freeze_order_")
            st.rerun()
        delete_index = None
        for idx, image_path in enumerate(list(pending["freeze_image_paths"]), start=1):
            cols = st.columns([0.18, 0.42, 0.18, 0.12, 0.1])
            with cols[0]:
                st.write(f"Ảnh {idx}")
            with cols[1]:
                st.caption(Path(image_path).name)
            with cols[2]:
                st.caption(f"{st.session_state.get(f'image_to_video_freeze_seconds_{idx}', 2)}s")
            with cols[3]:
                st.caption(f"Thứ tự: {st.session_state.get(f'image_to_video_freeze_order_{idx}', idx)}")
            with cols[4]:
                if st.button("Xóa", key=f"delete_image_to_video_freeze_{idx}"):
                    delete_index = idx - 1
        if delete_index is not None:
            pending["freeze_image_paths"].pop(delete_index)
            st.session_state["pending_image_to_video_request"] = pending
            _clear_freeze_state("image_to_video_freeze_seconds_")
            _clear_freeze_state("image_to_video_freeze_order_")
            st.rerun()

    freeze_seconds: list[int] = []
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
                        key=f"image_to_video_freeze_seconds_{idx}",
                    )
                )
            with cols[3]:
                st.number_input(
                    f"Thứ tự ảnh {idx}",
                    min_value=1,
                    max_value=len(pending["freeze_image_paths"]),
                    value=idx,
                    step=1,
                    key=f"image_to_video_freeze_order_{idx}",
                )

    total_freeze_seconds = sum(int(x) for x in freeze_seconds) if freeze_seconds else 0
    projected_total = int(pending["duration"]) + total_freeze_seconds
    base_estimate_key = "video_lite_8s_usd" if pending["model_label"] == "Veo 3.1 Lite" else "video_standard_8s_usd"
    base_estimate_usd = float(
        config.get("cost_estimates", {}).get(
            base_estimate_key,
            0.35 if pending["model_label"] == "Veo 3.1 Lite" else 1.0,
        )
    )
    base_estimate_vnd = base_estimate_usd * float(config.get("billing", {}).get("usd_to_vnd", config["cost_guard"].get("usd_to_vnd", 25000)))
    st.warning(f"Chi phí ước tính: ${base_estimate_usd:.2f} USD / {base_estimate_vnd:,.0f} VND")
    st.info(f"Tổng thời lượng dự kiến cuối: {projected_total}s")
    if pending.get("freeze_image_paths"):
        st.caption("Ảnh sẽ được ghép theo thứ tự bạn chọn.")

    if not use_credit:
        st.warning("Vui lòng xác nhận trước khi tạo.")
        return
    if not pending.get("selected_image_path") or not Path(pending["selected_image_path"]).exists():
        st.error("Chưa có ảnh đầu vào.")
        return

    if st.button("Tạo video từ ảnh", key="run_image_to_video_now"):
        progress = st.progress(0, text="Đang chuẩn bị")
        prompt = _build_motion_prompt(pending.get("selected_character"), pending["prompt"])
        request_id = log_request(
            "image_to_video",
            pending["campaign_id"],
            "image to video request",
            model=pending["model_label"],
            prompt=prompt,
            status="generating",
        )
        save_prompt(
            {
                "campaign_id": pending["campaign_id"],
                "type": "image_to_video",
                "prompt": prompt,
                "negative_prompt": "",
                "model": pending["model_label"],
                "aspect_ratio": pending["aspect_ratio"],
                "status": "generating",
            }
        )
        estimated_usd = base_estimate_usd
        estimated_vnd = base_estimate_vnd
        log_usage_cost(
            request_id=request_id,
            project_id=st.session_state["project_id"],
            model=pending["model_label"],
            media_type="image_to_video",
            estimated_cost_usd=estimated_usd,
            estimated_cost_vnd=estimated_vnd,
        )

        status = st.empty()
        status.info("Đang gửi request")
        output_dir = _video_output_dir("Chiến_dịch_mặc_định")
        output_path = output_dir / f"image_to_video_{datetime.now().strftime('%H%M%S')}.mp4"

        try:
            video_model = config["vertex"]["models"].get(
                "video_lite" if pending["model_label"] == "Veo 3.1 Lite" else "video_standard"
            )
            if not video_model:
                st.error("Chưa cấu hình model")
                return
            client = VertexClient(
                project_id=st.session_state["project_id"],
                region=st.session_state["region"],
                imagen_model=config["vertex"]["models"].get("image_standard", ""),
                veo_model=video_model,
                api_key=st.session_state.get("api_key"),
            )
            progress.progress(20, text="Đang gửi request lên Vertex AI")
            status.info("Đang chờ Veo xử lý")
            output_path = Path(
                client.generate_video_from_image(
                    prompt=prompt,
                    model=video_model,
                    aspect_ratio=pending["aspect_ratio"],
                    duration_seconds=pending["duration"],
                    image_path=pending["selected_image_path"],
                    output_dir=str(output_dir),
                    generate_audio=bool(pending.get("generate_audio", True)),
                )
            )
            progress.progress(65, text="Đang nối ảnh ở đuôi video")
            if pending.get("freeze_image_paths"):
                extended_parts = [str(output_path)]
                ordered_items = sorted(
                    [
                        (
                            int(st.session_state.get(f"image_to_video_freeze_order_{idx}", idx)),
                            idx,
                            image_path,
                        )
                        for idx, image_path in enumerate(pending["freeze_image_paths"], start=1)
                    ],
                    key=lambda item: (item[0], item[1]),
                )
                for _, idx, image_path in ordered_items:
                    seconds = int(st.session_state.get(f"image_to_video_freeze_seconds_{idx}", 2))
                    freeze_clip = output_dir / f"freeze_{idx}_{datetime.now().strftime('%H%M%S')}.mp4"
                    _make_freeze_clip(image_path, pending["aspect_ratio"], seconds, str(freeze_clip))
                    extended_parts.append(str(freeze_clip))
                if len(extended_parts) > 1:
                    progress.progress(82, text="Đang ghép video và ảnh")
                    final_output = output_dir / f"extended_{datetime.now().strftime('%H%M%S')}.mp4"
                    _concat_videos(extended_parts, str(final_output))
                    output_path = final_output
            progress.progress(92, text="Đang lưu video về máy")
            update_request_status(request_id, "completed", output_path=str(output_path), detail="Vertex AI image-to-video")
            progress.progress(100, text="Hoàn thành")
            st.success("Hoàn thành")
            st.video(str(output_path))
            st.caption(str(output_path))
            st.caption(prompt)
            if st.button("Mở thư mục video", key="open_image_to_video_folder"):
                _open_folder(str(output_path))
            return
        except Exception as exc:
            update_request_status(request_id, "failed", detail=str(exc))
            progress.progress(100, text="Thất bại")
            st.error(f"Lỗi: {exc}")
            return
