from __future__ import annotations

TEXT = {
    "app_title": "Studio Marketing Bảo Ngọc : Mẹo Thi HSK - JLPT -TOCFL",
    "app_subtitle": "Công cụ tạo ảnh/video marketing bằng Vertex AI",
    "sidebar_project": "Dự án",
    "sidebar_vertex_project": "Project Vertex",
    "sidebar_region": "Khu vực",
    "sidebar_usage": "Mức sử dụng",
    "tab_campaigns": "Chiến dịch",
    "tab_images": "Tạo ảnh",
    "tab_videos": "Tạo video",
    "tab_editor": "Biên tập video",
    "tab_subtitles": "Phụ đề",
    "tab_characters": "Nhân vật",
    "tab_image_to_video": "Tạo video từ ảnh",
    "tab_long_video": "Tạo video dài",
    "tab_qr_cta": "QR / CTA",
    "tab_presets": "Mẫu prompt",
    "campaign_manager": "Quản lý chiến dịch",
    "campaign_name": "Tên chiến dịch",
    "platform": "Nền tảng",
    "aspect_ratio": "Tỷ lệ khung hình",
    "style_preset": "Phong cách",
    "create_campaign": "Tạo chiến dịch",
    "campaign_list": "Danh sách chiến dịch",
    "prompt_list": "Danh sách prompt",
    "empty": "Chưa có dữ liệu",
    "image_generator": "Tạo ảnh",
    "prompt": "Mô tả",
    "negative_prompt": "Điều cần tránh",
    "model": "Model",
    "aspect_image": "Tỷ lệ ảnh",
    "num_images": "Số lượng ảnh",
    "estimate_cost": "Ước tính chi phí",
    "confirm_generation": "Xác nhận tạo",
    "generate_image": "Tạo ảnh",
    "output": "Kết quả",
    "preview": "Xem trước",
    "error": "Lỗi",
    "safety_blocked": "Bị chặn bởi chính sách an toàn",
    "video_generator": "Tạo video",
    "duration": "Thời lượng",
    "generate_audio": "Tạo âm thanh",
    "estimated_cost": "Chi phí ước tính",
    "confirm_video": "Tôi xác nhận tạo video và sử dụng credit Google Cloud",
    "generate_video": "Tạo video",
    "output_video": "Video kết quả",
    "merge_videos": "Nối video",
    "trim_video": "Cắt video",
    "resize": "Đổi kích thước",
    "intro_text": "Chữ mở đầu",
    "outro_text": "Chữ kết thúc",
    "export": "Xuất video",
    "select_videos": "Chọn video",
    "start_time": "Thời điểm bắt đầu",
    "end_time": "Thời điểm kết thúc",
    "subtitle_text": "Nội dung phụ đề",
    "generate_srt": "Tạo file SRT",
    "burn_subtitles": "Gắn phụ đề vào video",
    "upload_srt": "Tải file SRT lên",
    "export_subtitle": "Xuất phụ đề",
    "preset_prompts": "Mẫu prompt có sẵn",
    "copy_prompt": "Sao chép prompt",
    "status_queued": "Đang chờ",
    "status_generating": "Đang tạo",
    "status_completed": "Hoàn thành",
    "status_failed": "Thất bại",
    "saved_to": "Đã lưu tại",
    "request_logged": "Đã ghi log request",
    "missing_credentials": "Thiếu thông tin xác thực Google Cloud",
    "model_not_configured": "Chưa cấu hình model",
    "please_confirm_before_generating": "Vui lòng xác nhận trước khi tạo",
    "created_campaign": "Đã tạo chiến dịch #{}",
    "queued_prompt": "Đã xếp hàng prompt #{}",
    "loaded_config_missing": "Thiếu config.yaml hoặc giá trị cấu hình",
    "no_data": "Chưa có dữ liệu",
    "select_model": "Chọn model",
    "select_video": "Chọn video",
    "recent_history": "Lịch sử tạo gần đây",
    "request_type": "Loại",
    "created_at": "Thời gian tạo",
}


STATUS_MAP = {
    "queued": TEXT["status_queued"],
    "generating": TEXT["status_generating"],
    "completed": TEXT["status_completed"],
    "failed": TEXT["status_failed"],
}


def t(key: str, default: str | None = None, **kwargs) -> str:
    text = TEXT.get(key, default if default is not None else key)
    if kwargs:
        return text.format(**kwargs)
    return text


def status_label(value: str | None) -> str:
    if not value:
        return ""
    return STATUS_MAP.get(value, value)
