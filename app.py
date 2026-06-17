import streamlit as st

from src.billing_tracker import render_credit_sidebar
from src.characters import render_characters_tab
from src.cost_guard import summarize_usage
from src.database import init_db, list_campaigns, list_prompts, list_recent_requests, create_campaign
from src.gcloud_profiles import render_gcloud_profile_sidebar
from src.subtitle_tools import render_subtitle_tab
from src.video_editor import render_editor_tab
from src.image_generator import render_image_tab
from src.image_to_video import render_image_to_video_tab
from src.i18n import t, status_label
from src.prompt_presets import DISPLAY_NAMES_VI, PRESETS
from src.utils import ensure_app_dirs, load_config
from src.video_generator import render_video_tab


APP_TITLE = t("app_title")


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    ensure_app_dirs()
    init_db()
    config = load_config()

    st.title(APP_TITLE)
    st.caption(t("app_subtitle"))

    campaigns = list_campaigns()
    if not campaigns:
        default_campaign_id = create_campaign(
            {
                "campaign_name": "Chiến dịch mặc định",
                "platform": "TikTok",
                "aspect_ratio": "9:16",
                "style_preset": "App Promo",
            }
        )
        campaigns = list_campaigns()
    else:
        default_campaign_id = campaigns[0]["id"]

    with st.sidebar:
        render_gcloud_profile_sidebar(config)
        render_credit_sidebar(config, st.session_state.get("project_id"))
        st.header(t("sidebar_project"))
        project_id = st.selectbox(
            t("sidebar_vertex_project"),
            config["vertex"]["project_ids"],
            index=0,
        )
        region = st.selectbox(t("sidebar_region"), config["vertex"]["regions"], index=0)
        api_key = st.text_input("API key fallback", type="password")
        st.session_state["project_id"] = project_id
        st.session_state["region"] = region
        st.session_state["vertex_api_key"] = api_key
        st.session_state["daily_limit_vnd"] = config["cost_guard"]["daily_limit_vnd"]
        st.divider()
        st.subheader(t("sidebar_usage"))
        usage = summarize_usage()
        st.write(usage)

    tabs = st.tabs(
        [
            t("tab_campaigns"),
            t("tab_images"),
            t("tab_videos"),
            t("tab_editor"),
            t("tab_subtitles"),
            t("tab_characters"),
            t("tab_image_to_video"),
            t("tab_presets"),
        ]
    )

    with tabs[0]:
        st.subheader(t("campaign_manager"))
        with st.form("campaign_form"):
            campaign_name = st.text_input(t("campaign_name"), value="Chiến dịch mặc định")
            platform = st.selectbox(t("platform"), ["TikTok", "Facebook", "YouTube", "Google Play"])
            aspect_ratio = st.selectbox(t("aspect_ratio"), ["9:16", "16:9", "1:1"])
            style_preset = st.selectbox(t("style_preset"), [DISPLAY_NAMES_VI[k] for k in PRESETS.keys()])
            submitted = st.form_submit_button(t("create_campaign"))
        if submitted:
            campaign_id = create_campaign(
                {
                    "campaign_name": campaign_name,
                    "platform": platform,
                    "aspect_ratio": aspect_ratio,
                    "style_preset": style_preset,
                }
            )
            st.success(f"Đã tạo chiến dịch #{campaign_id}")

        st.markdown(f"### {t('campaign_list')}")
        campaigns = list_campaigns()
        if campaigns:
            st.dataframe(campaigns, use_container_width=True)
        else:
            st.info(t("empty"))
        st.markdown(f"### {t('prompt_list')}")
        prompts = list_prompts()
        if prompts:
            translated_prompts = []
            for row in prompts:
                item = dict(row)
                item["status"] = status_label(item.get("status"))
                translated_prompts.append(item)
            st.dataframe(translated_prompts, use_container_width=True)
        else:
            st.info(t("empty"))

        st.markdown(f"### {t('recent_history')}")
        recent = list_recent_requests(20)
        if recent:
            translated_recent = []
            for row in recent:
                item = dict(row)
                item["status"] = status_label(item.get("status"))
                item["request_type"] = "Ảnh" if item.get("request_type") == "image" else "Video" if item.get("request_type") == "video" else item.get("request_type")
                translated_recent.append(item)
            st.dataframe(translated_recent, use_container_width=True)
        else:
            st.info(t("empty"))

    with tabs[1]:
        render_image_tab(default_campaign_id, config)

    with tabs[2]:
        render_video_tab(default_campaign_id, config)

    with tabs[3]:
        render_editor_tab()

    with tabs[4]:
        render_subtitle_tab()

    with tabs[5]:
        render_characters_tab()

    with tabs[6]:
        render_image_to_video_tab(config, default_campaign_id)

    with tabs[7]:
        st.subheader(t("preset_prompts"))
        for name, prompt in PRESETS.items():
            label = DISPLAY_NAMES_VI.get(name, name)
            st.write(f"**{label}**")
            st.code(prompt)

if __name__ == "__main__":
    main()
