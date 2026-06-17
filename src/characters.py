from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import streamlit as st

from .database import create_character, get_character_by_slug, list_characters, save_ui_state
from .utils import root_path


PRESET_CHARACTERS = [
    {
        "name": "Cô giáo Linh Nhi",
        "role": "Đại sứ thương hiệu / giáo viên HSK",
        "description": "Cô giáo Trung Quốc trẻ, xinh đẹp, thanh lịch, mặc hanfu xanh trắng, phong cách tiên nữ giáo dục cao cấp, chuyên dạy HSK cho học viên Việt Nam.",
        "base_prompt": "Linh Nhi Teacher, beautiful young Chinese language teacher, elegant light blue and white hanfu, graceful and intelligent, premium Chinese fantasy movie quality, professional educational brand ambassador, teaching HSK, warm trustworthy smile, cinematic lighting, no text, no watermark.",
    },
    {
        "name": "Nam học viên Việt Nam",
        "role": "Đại diện người học",
        "description": "Nam sinh viên Việt Nam 20-24 tuổi, thân thiện, chăm chỉ, học tiếng Trung trên điện thoại, luyện thi HSK.",
        "base_prompt": "Young Vietnamese university student, friendly and hardworking, learning Chinese on smartphone, HSK exam preparation, modern casual outfit, motivated expression, cinematic educational advertisement, no text, no watermark.",
    },
]


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")


def save_reference_image(uploaded_file, character_slug: str) -> str:
    folder = root_path("data", "characters", character_slug)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / uploaded_file.name
    target.write_bytes(uploaded_file.read())
    return str(target)


def render_characters_tab() -> None:
    st.subheader("Nhân vật")

    with st.expander("Tạo nhân vật mới", expanded=True):
        preset = st.selectbox("Preset", ["", *[item["name"] for item in PRESET_CHARACTERS]])
        if preset:
            preset_data = next(item for item in PRESET_CHARACTERS if item["name"] == preset)
        else:
            preset_data = {"name": "", "role": "", "description": "", "base_prompt": ""}
        with st.form("character_form"):
            name = st.text_input("Tên nhân vật", value=preset_data.get("name", ""))
            role = st.text_input("Vai trò", value=preset_data.get("role", ""))
            description = st.text_area("Mô tả ngoại hình", value=preset_data.get("description", ""))
            base_prompt = st.text_area("Prompt nền", value=preset_data.get("base_prompt", ""))
            reference = st.file_uploader("Ảnh tham chiếu chính", type=["png", "jpg", "jpeg"])
            submitted = st.form_submit_button("Lưu nhân vật")
        if submitted and name:
            slug = slugify(name)
            reference_path = None
            if reference:
                reference_path = save_reference_image(reference, slug)
            character_id = create_character(
                {
                    "name": name,
                    "slug": slug,
                    "role": role,
                    "description": description,
                    "base_prompt": base_prompt,
                    "reference_image_path": reference_path,
                }
            )
            st.success(f"Đã lưu nhân vật: {name} (#{character_id})")

    st.markdown("### Danh sách nhân vật")
    characters = list_characters()
    if not characters:
        st.info("Chưa có dữ liệu")
        return

    for row in characters:
        with st.container(border=True):
            st.write(f"**{row['name']}**")
            st.write(row.get("role") or "")
            st.write(row.get("description") or "")
            if row.get("reference_image_path") and Path(row["reference_image_path"]).exists():
                st.image(row["reference_image_path"], width=220)
            if st.button("Dùng nhân vật này trong prompt", key=f"use_character_{row['slug']}"):
                st.session_state["selected_character"] = row
                save_ui_state("selected_character_slug", row["slug"])
                st.success(f"Đã chọn {row['name']}")


def get_selected_character() -> dict | None:
    if st.session_state.get("selected_character"):
        return st.session_state.get("selected_character")
    from .database import get_ui_state

    slug = get_ui_state("selected_character_slug")
    if slug:
        character = get_character_by_slug(slug)
        if character:
            st.session_state["selected_character"] = character
            return character
    return None
