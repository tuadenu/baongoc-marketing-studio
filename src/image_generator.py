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
from .i18n import t
from .prompt_presets import PRESETS
from .utils import root_path
from .vertex_client import VertexClient


IMAGE_COSTS_USD = {
    "Imagen 4 Fast": 0.02,
    "Imagen 4": 0.04,
    "Imagen 4 Ultra": 0.08,
}


def _estimate_image_cost_usd(config: dict, model_label: str) -> float:
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


def render_image_tab(default_campaign_id: int, config: dict) -> None:
    st.subheader(t("image_generator"))
    pending = st.session_state.get("pending_image_request")
    last_prompt = get_ui_state("image_prompt", PRESETS["App Promo"]) or PRESETS["App Promo"]
    last_negative = get_ui_state("image_negative_prompt", "no watermark, no text") or "no watermark, no text"
    last_aspect = get_ui_state("image_aspect_ratio", "1:1") or "1:1"
    last_num_images = int(get_ui_state("image_num_images", "1") or 1)
    last_model = get_ui_state("image_model_label", "Imagen 4 Fast") or "Imagen 4 Fast"
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
        }

    if not pending:
        return

    usd = IMAGE_COSTS_USD[pending["model_label"]] * pending["num_images"]
    vnd = usd * float(config["cost_guard"].get("usd_to_vnd", 25000))
    st.warning(f"{t('estimate_cost')}: ${usd:.2f} USD / {vnd:,.0f} VND")
    confirm = st.checkbox(t("confirm_generation"), key="confirm_image_generate")
    if confirm and st.button("Tạo ảnh", key="run_image_now"):
        progress = st.progress(0, text="Đang chuẩn bị")
        image_model = config["vertex"]["models"].get(pending["model_key"])
        if not image_model:
            st.error(t("model_not_configured"))
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
            log_usage_cost(
                request_id=request_id,
                project_id=st.session_state["project_id"],
                model=pending["model_label"],
                media_type="image",
                estimated_cost_usd=estimated_usd,
                estimated_cost_vnd=estimated_vnd,
            )
            try:
                progress.progress(35, text="Đang tạo ảnh")
                output_path = client.generate_image(
                    prompt=pending["prompt"],
                    model=image_model,
                    aspect_ratio=pending["aspect_ratio"],
                    output_dir=str(output_dir),
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
                if "safety" in message.lower() or "blocked" in message.lower():
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
            if st.button("Mở thư mục ảnh", key="open_image_folder"):
                _open_folder(first_output)
        st.session_state.pop("pending_image_request", None)
