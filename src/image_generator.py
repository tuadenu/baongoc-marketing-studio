from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import streamlit as st

from .database import (
    get_ui_state,
    log_request,
    log_usage_cost,
    save_prompt,
    save_ui_state,
    update_prompt_status,
    update_request_status,
)
from .characters import list_characters
from .i18n import t
from .prompt_presets import PRESETS
from .qr_tools import apply_qr_cta_pipeline, render_pre_generate_qr_controls, render_qr_postprocess_controls
from .utils import root_path
from .vertex_client import VertexClient


IMAGE_COSTS_USD = {
    "Imagen 4 Fast": 0.02,
    "Imagen 4": 0.04,
    "Imagen 4 Ultra": 0.08,
}

IMAGE_EDIT_COSTS_USD = {
    "Nano Banana": 0.04,
    "Nano Banana Pro": 0.08,
    "Gemini image edit": 0.04,
}

IMAGE_EDIT_MODEL_KEYS = {
    "Nano Banana": "image_edit_nano_banana",
    "Nano Banana Pro": "image_edit_nano_banana_pro",
    "Gemini image edit": "image_edit_gemini",
}


def _estimate_image_cost_usd(config: dict, model_label: str) -> float:
    if model_label in IMAGE_EDIT_COSTS_USD:
        return float(config.get("cost_estimates", {}).get(f"{model_label.lower().replace(' ', '_')}_usd", IMAGE_EDIT_COSTS_USD[model_label]))
    key_map = {
        "Imagen 4 Fast": "image_fast_usd",
        "Imagen 4": "image_standard_usd",
        "Imagen 4 Ultra": "image_ultra_usd",
    }
    return float(config.get("cost_estimates", {}).get(key_map[model_label], IMAGE_COSTS_USD[model_label]))


def _image_output_dir(campaign_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d")
    out_dir = root_path("outputs", "images", stamp, campaign_name.replace(" ", "_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _open_folder(path: str) -> None:
    try:
        subprocess.run(["open", str(Path(path).parent)], check=False)
    except Exception:
        pass


def _open_folder_from_state(state_key: str) -> None:
    path = st.session_state.get(state_key)
    if path:
        _open_folder(path)


def list_generated_images() -> list[str]:
    image_root = root_path("outputs", "images")
    files = sorted([str(p) for p in image_root.rglob("*.png")] + [str(p) for p in image_root.rglob("*.jpg")] + [str(p) for p in image_root.rglob("*.jpeg")])
    return files


def list_character_reference_images() -> list[str]:
    characters = list_characters()
    files: list[str] = []
    for row in characters:
        path = row.get("reference_image_path")
        if path and Path(path).exists():
            files.append(path)
    return files


def save_uploaded_reference_image(uploaded_file) -> str:
    target_dir = root_path("data", "uploads")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / uploaded_file.name
    target.write_bytes(uploaded_file.read())
    return str(target)


def _edit_output_dir(campaign_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d")
    out_dir = root_path("outputs", "images", "edit", stamp, campaign_name.replace(" ", "_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _load_default_reference_image(selected_path: str | None) -> str | None:
    if selected_path and Path(selected_path).exists():
        return selected_path
    last = get_ui_state("image_reference_path")
    if last and Path(last).exists():
        return last
    return None


def generate_image_from_reference(client: VertexClient, model: str, prompt: str, aspect_ratio: str, reference_image_path: str, output_dir: str, negative_prompt: str, num_images: int) -> list[str]:
    return client.generate_image_from_reference(
        prompt=prompt,
        model=model,
        aspect_ratio=aspect_ratio,
        reference_image_path=reference_image_path,
        output_dir=output_dir,
        negative_prompt=negative_prompt,
        keep_face=True,
        num_images=num_images,
    )


def render_image_tab(default_campaign_id: int, config: dict) -> None:
    st.subheader(t("image_generator"))
    pending = st.session_state.get("pending_image_request")
    last_output_path = st.session_state.get("last_image_output_path")
    if last_output_path and Path(last_output_path).exists():
        st.image(last_output_path, caption=f"{t('preview')}: {last_output_path}", use_container_width=True)
        st.code(last_output_path)
    source_mode = st.radio("Nguồn tạo ảnh", ["Tạo từ prompt", "Tạo từ ảnh tham chiếu"], index=0 if get_ui_state("image_source_mode", "Tạo từ prompt") == "Tạo từ prompt" else 1, horizontal=True)
    save_ui_state("image_source_mode", source_mode)
    last_prompt = get_ui_state("image_prompt", PRESETS["App Promo"]) or PRESETS["App Promo"]
    last_negative = get_ui_state("image_negative_prompt", "no watermark, no text") or "no watermark, no text"
    last_aspect = get_ui_state("image_aspect_ratio", "1:1") or "1:1"
    last_num_images = int(get_ui_state("image_num_images", "1") or 1)
    last_model = get_ui_state("image_model_label", "Imagen 4 Fast") or "Imagen 4 Fast"
    if source_mode == "Tạo từ prompt":
        with st.form("image_form"):
            prompt = st.text_area(t("prompt"), value=last_prompt)
            negative_prompt = st.text_input(t("negative_prompt"), value=last_negative)
            aspect_ratio = st.selectbox(t("aspect_image"), ["1:1", "9:16", "16:9", "4:5"], index=["1:1", "9:16", "16:9", "4:5"].index(last_aspect) if last_aspect in ["1:1", "9:16", "16:9", "4:5"] else 0)
            num_images = st.number_input(t("num_images"), min_value=1, max_value=8, value=last_num_images)
            model = st.selectbox("Model", ["Imagen 4 Fast", "Imagen 4", "Imagen 4 Ultra"], index=["Imagen 4 Fast", "Imagen 4", "Imagen 4 Ultra"].index(last_model) if last_model in ["Imagen 4 Fast", "Imagen 4", "Imagen 4 Ultra"] else 0)
            submitted = st.form_submit_button("Xem chi phí ước tính")
        if submitted:
            save_ui_state("image_prompt", prompt)
            save_ui_state("image_negative_prompt", negative_prompt)
            save_ui_state("image_aspect_ratio", aspect_ratio)
            save_ui_state("image_num_images", str(int(num_images)))
            save_ui_state("image_model_label", model)
            st.session_state["pending_image_request"] = {
                "campaign_id": default_campaign_id,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "aspect_ratio": aspect_ratio,
                "num_images": int(num_images),
                "model_label": model,
                "model_key": {
                    "Imagen 4 Fast": "image_fast",
                    "Imagen 4": "image_standard",
                    "Imagen 4 Ultra": "image_ultra",
                }[model],
                "source_mode": source_mode,
            }
    else:
        with st.form("image_reference_form"):
            source_choice = st.radio(
                "Chọn nguồn ảnh",
                ["Upload ảnh từ máy", "Chọn từ ảnh đã tạo", "Chọn từ ảnh nhân vật"],
                index=0,
                horizontal=False,
            )
            reference_image_path = None
            if source_choice == "Upload ảnh từ máy":
                uploaded = st.file_uploader("Ảnh tham chiếu", type=["png", "jpg", "jpeg"])
                if uploaded:
                    reference_image_path = save_uploaded_reference_image(uploaded)
            elif source_choice == "Chọn từ ảnh đã tạo":
                files = list_generated_images()
                reference_image_path = st.selectbox("Ảnh đã tạo", files) if files else None
            else:
                files = list_character_reference_images()
                reference_image_path = st.selectbox("Ảnh nhân vật", files) if files else None

            if reference_image_path and Path(reference_image_path).exists():
                st.image(reference_image_path, caption="Ảnh gốc", use_container_width=True)
                save_ui_state("image_reference_path", reference_image_path)

            prompt = st.text_area(
                "Prompt chỉnh sửa",
                value=get_ui_state("image_edit_prompt", "Giữ nguyên khuôn mặt, tóc, dáng người và phong cách nhân vật trong ảnh gốc. Đưa nhân vật vào lớp học HSK hiện đại, ánh sáng điện ảnh, phong cách quảng cáo giáo dục cao cấp, màu sắc sạch và chuyên nghiệp.")
                or "Giữ nguyên khuôn mặt, tóc, dáng người và phong cách nhân vật trong ảnh gốc. Đưa nhân vật vào lớp học HSK hiện đại, ánh sáng điện ảnh, phong cách quảng cáo giáo dục cao cấp, màu sắc sạch và chuyên nghiệp.",
            )
            if st.checkbox("Giảm prompt xuống mức tối thiểu", value=False):
                prompt = "Giữ nguyên nhân vật chính trong ảnh gốc, thay đổi bối cảnh theo prompt."
            negative_prompt = st.text_input("Điều cần tránh", value=get_ui_state("image_edit_negative_prompt", "no watermark, no text") or "no watermark, no text")
            keep_face = st.checkbox("Giữ khuôn mặt/nhân vật giống ảnh gốc nhất có thể", value=True)
            aspect_ratio = st.selectbox("Tỷ lệ ảnh", ["1:1", "9:16", "16:9", "4:3", "3:4"], index=["1:1", "9:16", "16:9", "4:3", "3:4"].index(get_ui_state("image_edit_aspect_ratio", "1:1") or "1:1") if (get_ui_state("image_edit_aspect_ratio", "1:1") or "1:1") in ["1:1", "9:16", "16:9", "4:3", "3:4"] else 0)
            st.warning("Muốn giữ mặt/nhân vật, bắt buộc dùng image editing model thật. Imagen text-to-image không giữ được ảnh gốc.")
            model_options = ["Nano Banana", "Nano Banana Pro", "Gemini image edit"]
            model = st.selectbox("Model", model_options, index=0)
            model_key = IMAGE_EDIT_MODEL_KEYS[model]
            if not config["vertex"]["models"].get(model_key):
                st.error("Model này chưa được cấu hình trong config.yaml. Hãy điền model id thật cho image editing model.")
            num_images = st.number_input("Số lượng ảnh", min_value=1, max_value=8, value=int(get_ui_state("image_edit_num_images", "1") or 1))
            submitted = st.form_submit_button("Xem chi phí ước tính")
        if submitted:
            save_ui_state("image_edit_prompt", prompt)
            save_ui_state("image_edit_negative_prompt", negative_prompt)
            save_ui_state("image_edit_aspect_ratio", aspect_ratio)
            save_ui_state("image_edit_model_label", model)
            save_ui_state("image_edit_num_images", str(int(num_images)))
            if reference_image_path:
                save_ui_state("image_reference_path", reference_image_path)
            st.session_state["pending_image_request"] = {
                "campaign_id": default_campaign_id,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "aspect_ratio": aspect_ratio,
                "num_images": int(num_images),
                "model_label": model,
                "model_key": model_key,
                "source_mode": source_mode,
                "reference_image_path": reference_image_path,
                "keep_face": keep_face,
            }

    if not pending:
        return

    if pending.get("source_mode") == "Tạo từ ảnh tham chiếu":
        st.warning("Muốn giữ mặt/nhân vật, bắt buộc dùng image editing model thật. Imagen text-to-image không giữ được ảnh gốc.")
        if not config["vertex"]["models"].get(pending["model_key"]):
            st.error("Model hiện tại chưa hỗ trợ sửa ảnh từ ảnh gốc. Hãy cấu hình model edit ảnh thật trong config.yaml.")
            return
        usd = 0.0
    else:
        usd = IMAGE_COSTS_USD[pending["model_label"]] * pending["num_images"]
        vnd = usd * float(config["cost_guard"].get("usd_to_vnd", 25000))
        st.warning(f"{t('estimate_cost')}: ${usd:.2f} USD / {vnd:,.0f} VND")
    qr_options = render_pre_generate_qr_controls(
        config=config,
        state_prefix="image_generate",
        media_kind="image",
        allow_end_screen=False,
    )
    confirm = st.checkbox(t("confirm_generation"), key="confirm_image_generate")
    if confirm and st.button("Tạo ảnh", key="run_image_now"):
        progress = st.progress(0, text="Đang chuẩn bị")
        image_model = config["vertex"]["models"].get(pending["model_key"])
        if not image_model:
            st.error("Model hiện tại chưa hỗ trợ sửa ảnh từ ảnh gốc. Vui lòng dùng model image editing thật.")
            return
        client = VertexClient(
            project_id=st.session_state["project_id"],
            region=st.session_state["region"],
            imagen_model=image_model,
            veo_model=config["vertex"]["models"].get("video_standard", ""),
            api_key=None,
        )
        output_dir = _image_output_dir("Chiến_dịch_mặc_định")
        first_output = None
        for _ in range(pending["num_images"]):
            progress.progress(10, text="Đang gửi request")
            estimated_usd = _estimate_image_cost_usd(config, pending["model_label"])
            estimated_vnd = estimated_usd * float(config.get("billing", {}).get("usd_to_vnd", config["cost_guard"].get("usd_to_vnd", 25000)))
            prompt_id = save_prompt(
                {
                    "campaign_id": pending["campaign_id"],
                    "type": "image",
                    "prompt": pending["prompt"],
                    "negative_prompt": pending["negative_prompt"],
                    "model": pending["model_label"],
                    "aspect_ratio": pending["aspect_ratio"],
                    "status": "generating",
                }
            )
            request_id = log_request(
                "image",
                pending["campaign_id"],
                "vertex image generation",
                model=pending["model_label"],
                prompt=pending["prompt"],
                status="generating",
            )
            try:
                progress.progress(35, text="Đang tạo ảnh")
                if pending.get("source_mode") == "Tạo từ ảnh tham chiếu":
                    if not pending.get("reference_image_path") or not Path(pending["reference_image_path"]).exists():
                        raise RuntimeError("Chưa có ảnh tham chiếu hợp lệ.")
                    image_model = config["vertex"]["models"].get(pending["model_key"])
                    if not image_model:
                        raise RuntimeError("Model hiện tại chưa hỗ trợ sửa ảnh từ ảnh gốc. Vui lòng dùng model image editing thật.")
                    output_paths = generate_image_from_reference(
                        client=client,
                        model=image_model,
                        prompt=pending["prompt"],
                        aspect_ratio=pending["aspect_ratio"],
                        reference_image_path=pending["reference_image_path"],
                        output_dir=str(_edit_output_dir("Chiến_dịch_mặc_định")),
                        negative_prompt=pending["negative_prompt"],
                        num_images=1,
                    )
                    output_path = output_paths[0]
                    log_usage_cost(
                        request_id=request_id,
                        project_id=st.session_state["project_id"],
                        model=pending["model_label"],
                        media_type="image_to_image",
                        estimated_cost_usd=0.0,
                        estimated_cost_vnd=0.0,
                    )
                else:
                    log_usage_cost(
                        request_id=request_id,
                        project_id=st.session_state["project_id"],
                        model=pending["model_label"],
                        media_type="image",
                        estimated_cost_usd=estimated_usd,
                        estimated_cost_vnd=estimated_vnd,
                    )
                    output_path = client.generate_image(
                        prompt=pending["prompt"],
                        model=image_model,
                        aspect_ratio=pending["aspect_ratio"],
                        output_dir=str(output_dir),
                    )
                output_path = apply_qr_cta_pipeline(
                    source_path=output_path,
                    config=config,
                    campaign_id=pending["campaign_id"],
                    options=qr_options,
                )
                progress.progress(80, text="Đang lưu ảnh về máy")
                update_prompt_status(prompt_id, "completed", output_path)
                update_request_status(request_id, "completed", output_path=output_path)
                st.caption(f"{t('saved_to')}: {output_path}")
                first_output = first_output or output_path
            except Exception as exc:
                update_prompt_status(prompt_id, "failed")
                update_request_status(request_id, "failed", detail=str(exc))
                message = str(exc)
                if pending.get("source_mode") == "Tạo từ ảnh tham chiếu":
                    st.error(message or "Model hiện tại chưa hỗ trợ sửa ảnh từ ảnh gốc. Vui lòng dùng model image editing thật.")
                elif "safety" in message.lower() or "blocked" in message.lower():
                    st.error(t("safety_blocked"))
                else:
                    st.error(f"{t('error')}: {message}")
                progress.progress(100, text="Thất bại")
                break

        if first_output:
            progress.progress(100, text="Hoàn thành")
            st.success(t("status_completed"))
            st.image(first_output, caption=f"{t('preview')}: {first_output}", use_container_width=True)
            st.code(first_output)
            st.session_state["last_image_output_path"] = first_output
            if st.button("Mở thư mục ảnh", key="open_image_folder"):
                _open_folder_from_state("last_image_output_path")
        st.session_state.pop("pending_image_request", None)
