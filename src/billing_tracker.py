from __future__ import annotations

import subprocess
from datetime import datetime

import streamlit as st

from .database import (
    get_total_estimated_usage_vnd as db_total_estimated_usage_vnd,
    get_usage_costs_by_model,
    list_billing_snapshots,
    save_billing_snapshot,
)


def get_adc_account() -> str | None:
    try:
        result = subprocess.run(
            ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
            check=False,
            capture_output=True,
            text=True,
        )
        account = (result.stdout or "").strip().splitlines()[0].strip() if (result.stdout or "").strip() else ""
        return account or None
    except Exception:
        return None


def get_quota_project(config: dict) -> str | None:
    try:
        from google.auth import default

        credentials, project_id = default()
        quota_project = getattr(credentials, "quota_project_id", None)
        if quota_project:
            return quota_project
        if project_id:
            return project_id
    except Exception:
        pass
    return config.get("project_id") or config.get("vertex", {}).get("project_ids", [None])[0]


def get_project_id(config: dict, selected_project_id: str | None = None) -> str | None:
    return selected_project_id or config.get("project_id") or config.get("vertex", {}).get("project_ids", [None])[0]


def get_total_estimated_usage_vnd(config: dict | None = None) -> float:
    config = config or {}
    total = db_total_estimated_usage_vnd()
    return float(total)


def get_calibration_factor(config: dict) -> float | None:
    billing = config.get("billing", {})
    factor = billing.get("calibration_factor")
    try:
        return float(factor) if factor is not None else None
    except Exception:
        return None


def get_remaining_credit_vnd(config: dict, selected_project_id: str | None = None) -> tuple[float, float]:
    starting = float(config.get("billing", {}).get("starting_credit_vnd", 0))
    used = get_total_estimated_usage_vnd(config)
    remaining = max(starting - used, 0)
    return used, remaining


def format_vnd(value: float) -> str:
    return f"{value:,.0f} đ"


def _calibrated_remaining_vnd(config: dict, app_used_vnd: float) -> float:
    billing = config.get("billing", {})
    starting = float(billing.get("starting_credit_vnd", 0))
    factor = get_calibration_factor(config) or 1.0
    if not billing.get("use_calibrated_estimate", False):
        return max(starting - app_used_vnd, 0)
    return max(starting - (app_used_vnd * factor), 0)


def render_credit_sidebar(config: dict, selected_project_id: str | None = None) -> None:
    billing = config.get("billing", {})
    account = get_adc_account()
    quota_project = get_quota_project(config)
    project_id = get_project_id(config, selected_project_id)
    used_vnd, remaining_vnd = get_remaining_credit_vnd(config, project_id)
    calibrated_remaining_vnd = _calibrated_remaining_vnd(config, used_vnd)
    calibration_factor = get_calibration_factor(config)
    starting = float(billing.get("starting_credit_vnd", 0))
    pct = (remaining_vnd / starting * 100) if starting else 0.0
    calibrated_pct = (calibrated_remaining_vnd / starting * 100) if starting else 0.0
    updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    latest_snapshot = next(iter(list_billing_snapshots(limit=1)), None)

    with st.container(border=True):
        st.markdown("### 💳 Credit Google Cloud")
        if account:
            st.write(f"Tài khoản: `{account}`")
        else:
            st.warning("Không đọc được tài khoản Google Cloud. Hãy chạy gcloud auth application-default login.")
            st.write("Tài khoản: `Không đọc được`")
        st.write(f"Project: `{project_id or 'Không rõ'}`")
        st.write(f"Quota project: `{quota_project or 'Không rõ'}`")
        if account and project_id and account != "halamchuc@gmail.com":
            st.warning(
                "Tài khoản gcloud hiện tại có thể không đúng với project này. Hãy chạy:\n"
                "gcloud config set account halamchuc@gmail.com\n"
                "gcloud auth application-default login --account=halamchuc@gmail.com\n"
                "gcloud auth application-default set-quota-project hsk-master-dc53b"
            )
        st.metric("Còn lại ước tính theo app", format_vnd(remaining_vnd), delta=f"-{format_vnd(used_vnd)}")
        if billing.get("use_calibrated_estimate", False):
            st.metric("Còn lại hiệu chỉnh", format_vnd(calibrated_remaining_vnd), delta=f"x{calibration_factor or 1.0:.2f}")
        st.progress(min(max(pct / 100.0, 0.0), 1.0))
        cols = st.columns(2)
        with cols[0]:
            st.write(f"Credit gốc: {format_vnd(starting)}")
            st.write(f"Đã dùng ước tính theo app: {format_vnd(used_vnd)}")
            st.write(f"Còn lại ước tính theo app: {format_vnd(remaining_vnd)}")
        with cols[1]:
            st.write(f"Còn lại chính thức: {format_vnd(float(latest_snapshot['official_remaining_vnd'])) if latest_snapshot else 'Chưa có'}")
            st.write(f"Đã dùng chính thức: {format_vnd(float(latest_snapshot['official_used_vnd'])) if latest_snapshot else 'Chưa có'}")
            st.write(f"Sai lệch: {format_vnd(float(latest_snapshot['difference_vnd'])) if latest_snapshot else 'Chưa có'}")
            if latest_snapshot and latest_snapshot.get("calibration_factor") is not None:
                st.write(f"Hệ số hiệu chỉnh: `x{float(latest_snapshot['calibration_factor']):.2f}`")
            else:
                st.write("Hệ số hiệu chỉnh: `Chưa có`")
            st.write(f"Còn lại: `{pct:.1f}%`")
            st.write(f"Còn lại hiệu chỉnh: `{calibrated_pct:.1f}%`")
            st.write(f"Cập nhật lần cuối: `{updated}`")
        if st.button("Làm mới credit", key="refresh_credit_sidebar_btn"):
            st.session_state["last_credit_sidebar_refresh_at"] = datetime.utcnow().isoformat()
            st.rerun()
        st.caption("Số app chỉ là ước tính nội bộ. Số chính thức nằm trong Google Cloud Billing.")

        with st.expander("Số chính thức từ Google Cloud", expanded=False):
            default_official_starting = float(latest_snapshot["official_starting_credit_vnd"]) if latest_snapshot and latest_snapshot.get("official_starting_credit_vnd") is not None else starting
            default_official_used = float(latest_snapshot["official_used_vnd"]) if latest_snapshot and latest_snapshot.get("official_used_vnd") is not None else 731804.0
            default_official_remaining = float(latest_snapshot["official_remaining_vnd"]) if latest_snapshot and latest_snapshot.get("official_remaining_vnd") is not None else 7168847.0
            official_starting = st.number_input("Credit gốc chính thức", min_value=0.0, value=default_official_starting, step=1000.0, format="%.0f", key="official_starting_credit_vnd_input")
            official_used = st.number_input("Đã dùng chính thức", min_value=0.0, value=default_official_used, step=1000.0, format="%.0f", key="official_used_vnd_input")
            official_remaining = st.number_input("Còn lại chính thức", min_value=0.0, value=default_official_remaining, step=1000.0, format="%.0f", key="official_remaining_vnd_input")
            updated_at = st.text_input("Thời điểm cập nhật", value=latest_snapshot["created_at"] if latest_snapshot else datetime.utcnow().isoformat(), key="official_billing_updated_at")
            calibration = (official_used / used_vnd) if used_vnd else None
            difference_vnd = official_used - used_vnd
            st.write(f"App ước tính đã dùng: {format_vnd(used_vnd)}")
            st.write(f"Sai lệch: {format_vnd(difference_vnd)}")
            st.write(f"Hệ số hiệu chỉnh: `{('x' + format(calibration, '.2f')) if calibration is not None else 'Không xác định'}`")
            if st.button("Lưu snapshot chính thức", key="save_billing_snapshot_btn"):
                save_billing_snapshot(
                    {
                        "project_id": project_id,
                        "official_starting_credit_vnd": official_starting,
                        "official_used_vnd": official_used,
                        "official_remaining_vnd": official_remaining,
                        "app_estimated_used_vnd": used_vnd,
                        "difference_vnd": difference_vnd,
                        "calibration_factor": calibration,
                        "created_at": updated_at,
                    }
                )
                st.success("Đã lưu snapshot billing")

        breakdown = get_usage_costs_by_model()
        if breakdown:
            st.markdown("**Phân bổ theo model**")
            for row in breakdown[:5]:
                st.write(
                    f"- `{row['model']}` ({row['media_type']}): {format_vnd(float(row['total_vnd']))} / {row['requests']} request"
                )
