from __future__ import annotations

import streamlit as st

from .i18n import t


def render_subtitle_tab() -> None:
    st.subheader(t("tab_subtitles"))
    st.text_area(t("subtitle_text"), value="Xin chào, hôm nay học HSK cùng Linh Nhi")
    st.text_area(t("upload_srt"), value="00:00-00:03 Xin chào, hôm nay học HSK cùng Linh Nhi")
    st.button(t("generate_srt"))
    st.button(t("burn_subtitles"))
