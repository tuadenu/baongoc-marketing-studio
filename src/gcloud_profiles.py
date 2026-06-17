from __future__ import annotations

import subprocess
from dataclasses import dataclass

import streamlit as st


@dataclass
class GCloudProfile:
    name: str
    account: str
    project_id: str
    quota_project: str


def load_profiles(config: dict) -> list[GCloudProfile]:
    profiles = []
    for item in config.get("gcloud_profiles", []) or []:
        try:
            profiles.append(
                GCloudProfile(
                    name=item["name"],
                    account=item["account"],
                    project_id=item["project_id"],
                    quota_project=item["quota_project"],
                )
            )
        except Exception:
            continue
    return profiles


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def get_active_gcloud_account() -> str | None:
    result = _run(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"])
    if result.returncode != 0:
        return None
    out = (result.stdout or "").strip().splitlines()
    return out[0].strip() if out else None


def get_active_gcloud_project() -> str | None:
    result = _run(["gcloud", "config", "get-value", "project"])
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value if value and value != "(unset)" else None


def get_adc_quota_project() -> str | None:
    try:
        from google.auth import default

        credentials, project_id = default()
        quota_project = getattr(credentials, "quota_project_id", None)
        return quota_project or project_id
    except Exception:
        return None


def _set_gcloud_value(args: list[str]) -> tuple[bool, str]:
    result = _run(args)
    if result.returncode == 0:
        return True, (result.stdout or "").strip()
    return False, (result.stderr or result.stdout or "Lỗi không xác định").strip()


def activate_profile(profile: GCloudProfile) -> tuple[bool, str]:
    steps = [
        ["gcloud", "config", "set", "account", profile.account],
        ["gcloud", "config", "set", "project", profile.project_id],
        ["gcloud", "auth", "application-default", "set-quota-project", profile.quota_project],
    ]
    messages = []
    for cmd in steps:
        ok, message = _set_gcloud_value(cmd)
        messages.append(message)
        if not ok:
            return False, "\n".join(messages)
    return True, "\n".join(messages)


def login_profile(profile: GCloudProfile) -> tuple[bool, str]:
    steps = [
        ["gcloud", "auth", "login", profile.account],
        ["gcloud", "auth", "application-default", "login", f"--account={profile.account}"],
    ]
    messages = []
    for cmd in steps:
        result = _run(cmd)
        messages.append((result.stdout or result.stderr or "").strip())
        if result.returncode != 0:
            return False, "\n".join(messages)
    ok, message = activate_profile(profile)
    messages.append(message)
    return ok, "\n".join(messages)


def render_gcloud_profile_sidebar(config: dict) -> None:
    profiles = load_profiles(config)
    if not profiles:
        return

    st.markdown("### 🔐 Google Cloud Profile")
    names = [profile.name for profile in profiles]
    selected_name = st.selectbox("Chọn profile", names, key="selected_gcloud_profile")
    profile = next((item for item in profiles if item.name == selected_name), profiles[0])

    st.write(f"**Account:** `{profile.account}`")
    st.write(f"**Project:** `{profile.project_id}`")
    st.write(f"**Quota project:** `{profile.quota_project}`")

    active_account = get_active_gcloud_account()
    active_project = get_active_gcloud_project()
    active_quota = get_adc_quota_project()
    st.caption(f"Active account: `{active_account or 'Không rõ'}`")
    st.caption(f"Active project: `{active_project or 'Không rõ'}`")
    st.caption(f"ADC quota project: `{active_quota or 'Không rõ'}`")

    needs_login = active_account != profile.account or active_project != profile.project_id
    if needs_login:
        st.warning(
            "Profile đã chọn chưa khớp với gcloud hiện tại hoặc ADC có thể chưa hợp lệ.\n"
            "Bạn có thể bấm Đăng nhập tài khoản này để mở trình duyệt đăng nhập."
        )

    confirmed = st.checkbox(
        "Tôi hiểu thao tác này sẽ đổi tài khoản/project Google Cloud đang active trên máy",
        key="confirm_gcloud_profile_switch",
    )
    if st.button("Kích hoạt profile", key="activate_gcloud_profile_btn"):
        if not confirmed:
            st.warning("Vui lòng tick xác nhận trước khi kích hoạt profile.")
        else:
            ok, message = activate_profile(profile)
            st.session_state["project_id"] = profile.project_id
            st.session_state["region"] = config.get("region", "us-central1")
            if ok:
                st.success("Kích hoạt profile thành công.")
            else:
                st.error(f"Thất bại khi kích hoạt profile:\n{message}")
            st.code(message or "Không có phản hồi")
            st.rerun()

    if needs_login:
        if st.button("Đăng nhập tài khoản này", key="login_gcloud_profile_btn"):
            st.info("Trình duyệt sẽ mở để bạn đăng nhập Google. Sau khi đăng nhập xong, quay lại app và bấm Kiểm tra trạng thái gcloud.")
            ok, message = login_profile(profile)
            if ok:
                st.success("Đăng nhập và kích hoạt profile thành công.")
                st.session_state["project_id"] = profile.project_id
                st.session_state["region"] = config.get("region", "us-central1")
                st.code(message or "Đã hoàn tất")
                st.rerun()
            st.error(f"Lỗi khi đăng nhập profile:\n{message}")
    st.code(
        "\n".join(
            [
                f"gcloud auth login {profile.account}",
                f"gcloud auth application-default login --account={profile.account}",
                f"gcloud config set account {profile.account}",
                f"gcloud config set project {profile.project_id}",
                f"gcloud auth application-default set-quota-project {profile.quota_project}",
            ]
        ),
        language="bash",
    )
    if st.button("Chỉ mở hướng dẫn đăng nhập", key="show_gcloud_login_guide_btn"):
        st.info("Sao chép các lệnh trong khung bên dưới và chạy trong Terminal.")

    if st.button("Kiểm tra trạng thái gcloud", key="check_gcloud_status_btn"):
        st.write(f"Account active hiện tại: `{get_active_gcloud_account() or 'Không rõ'}`")
        st.write(f"Project hiện tại: `{get_active_gcloud_project() or 'Không rõ'}`")
        st.write(f"ADC quota project: `{get_adc_quota_project() or 'Không rõ'}`")
