from __future__ import annotations

import streamlit as st

from .utils import load_config
from .vertex_client import VertexClient


def _model_groups(config: dict) -> dict[str, list[tuple[str, str]]]:
    models = config.get("vertex", {}).get("models", {})
    return {
        "image_text_models": [
            ("Imagen 4 Fast", models.get("image_fast", "")),
            ("Imagen 4", models.get("image_standard", "")),
            ("Imagen 4 Ultra", models.get("image_ultra", "")),
        ],
        "image_edit_models": [
            ("Nano Banana", models.get("image_edit_nano_banana", "")),
            ("Nano Banana Pro", models.get("image_edit_nano_banana_pro", "")),
            ("Gemini image edit", models.get("image_edit_gemini", "")),
        ],
        "video_models": [
            ("Veo 3.1 Lite", models.get("video_lite", "")),
            ("Veo 3.1", models.get("video_standard", "")),
        ],
    }


def render_model_checker_tab(config: dict | None = None) -> None:
    st.subheader("Kiểm tra model Vertex/Gemini")
    config = config or load_config()
    if st.button("Liệt kê model khả dụng", key="list_available_models_btn"):
        project_id = config.get("project_id") or config.get("vertex", {}).get("project_ids", [None])[0]
        region = config.get("region") or config.get("vertex", {}).get("regions", [None])[0] or "us-central1"
        try:
            client = VertexClient(
                project_id=project_id,
                region=region,
                imagen_model=config["vertex"]["models"].get("image_standard", ""),
                veo_model=config["vertex"]["models"].get("video_standard", ""),
                api_key=None,
            )
            pager = client._genai_client().models.list()
            st.success("Đã lấy danh sách model từ SDK.")
            rows = []
            for item in pager:
                rows.append(
                    {
                        "name": getattr(item, "name", ""),
                        "display_name": getattr(item, "display_name", "") or getattr(item, "displayName", ""),
                        "supported_actions": str(getattr(item, "supported_actions", "") or getattr(item, "supportedActions", "")),
                    }
                )
            if rows:
                st.dataframe(rows, use_container_width=True)
            else:
                st.info("Không có model nào từ SDK.")
        except Exception as exc:
            st.error(f"SDK không hỗ trợ list models trực tiếp hoặc không đọc được model. Lỗi: {exc}")
            st.code(
                "python scripts/check_models.py\n"
                "gcloud auth application-default login\n"
                "gcloud auth application-default set-quota-project <project_id>",
                language="bash",
            )
            return

    groups = _model_groups(config)
    st.markdown("### Model trong config.yaml")
    for group_name, items in groups.items():
        st.markdown(f"**{group_name}**")
        for label, model_id in items:
            if not model_id:
                st.write(f"- {label}: chưa cấu hình")
            else:
                st.write(f"- {label}: `{model_id}`")
