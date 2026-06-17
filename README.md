# Studio Marketing Mẹo Thi HSK

Ứng dụng Streamlit chạy local để tạo ảnh/video marketing cho app Mẹo Thi HSK bằng Vertex AI.

## Cài đặt

1. Tạo virtual environment trên macOS.
2. Cài `ffmpeg` bằng Homebrew:
   `brew install ffmpeg`
3. Cài dependencies:
   `pip install -r requirements.txt`

## Đăng nhập Google Cloud

Trước khi dùng profile trong app, hãy đăng nhập sẵn bằng terminal:

```bash
gcloud auth login <email>
gcloud auth application-default login --account=<email>
```

1. Đăng nhập ADC:
   `gcloud auth application-default login`
2. Gán quota project cho ADC:
   `gcloud auth application-default set-quota-project hsk-master-dc53b`
3. Chọn project mặc định:
   `gcloud config set project hsk-master-dc53b`

## Chạy app

```bash
cd /Users/phuonganh/Desktop/BaoNgoc-MarketingStudio/hsk_marketing_studio
source venv/bin/activate
streamlit run app.py
```

## Chạy bằng double click trên macOS

1. Double click `scripts/run_macos_app.command` để tự khởi động Streamlit ở cổng `8501` và mở trình duyệt.
2. Nếu server đã chạy rồi, double click `scripts/open_app.command` để chỉ mở `http://localhost:8501`.
3. Muốn tạo shortcut ngoài Desktop, hãy kéo file `.command` ra Desktop hoặc tạo alias từ Finder.

Lưu ý: icon web trong Chrome chỉ mở được khi Streamlit server đang chạy.

Trong sidebar, bạn có thể đổi giữa:
- `hsk-master-dc53b`
- `meothihsk-ai`

App cũng có mục `🔐 Google Cloud Profile` để chuyển nhanh giữa 2 profile Google Cloud.
Tính năng này chỉ đổi account/project/quota project đang active, không tự chạy login mới nếu bạn chưa đăng nhập sẵn.

## Credit Google Cloud

- Khối credit ở sidebar là số ước tính dựa trên request tạo từ app.
- Số chính thức vẫn xem trong Google Cloud Billing.
- Credit ban đầu, tỷ giá quy đổi, và thời hạn trial chỉnh trong `config.yaml` ở phần `billing`.
- Nếu muốn đổi số credit khởi điểm, sửa `billing.starting_credit_vnd`.
- Bảng ước tính chi phí từng loại media nằm ở `cost_estimates`.

## Nhân vật

- Tab `Nhân vật` cho phép lưu hồ sơ nhân vật marketing cho Mẹo Thi HSK.
- Ảnh reference được lưu vào `data/characters/<character_slug>/`.
- Có sẵn preset cho `Cô giáo Linh Nhi` và `Nam học viên Việt Nam`.
- Khi chọn một nhân vật, app sẽ ghép `base_prompt` của nhân vật vào prompt chuyển động.

## Tạo video từ ảnh

- Tab `Tạo video từ ảnh` cho phép chọn ảnh đã tạo, upload ảnh local, hoặc dùng ảnh reference của nhân vật.
- MVP hiện tại dùng fallback local để tạo mp4 từ ảnh, không tốn credit Veo.
- Video kết quả được lưu trong `outputs/videos/image_to_video/`.
- Khi cần kiểm tra lại luồng, bạn vẫn có thể dùng `scripts/test_vertex_image.py` và `scripts/test_vertex_video.py` như trước.

## Biên tập video

- Tab `Biên tập video` cho phép chọn nhiều video từ `outputs/videos/`, `outputs/videos/test/`, `outputs/videos/image_to_video/` hoặc upload từ máy.
- Có preset xuất cho TikTok/Reels/Shorts, YouTube và Facebook Post.
- Có thể chọn cách xử lý tỷ lệ: crop center, blur background hoặc pad black bars.
- Intro/outro được ghép bằng ffmpeg và file export luôn có timestamp, không ghi đè video gốc.
- Nếu chưa cài ffmpeg, app sẽ nhắc:
  `brew install ffmpeg`

## Phụ đề

- Tab `Phụ đề` cho phép nhập text thoại tiếng Việt và tự chia dòng phụ đề.
- Có thể tạo file `.srt` mới hoặc upload file `.srt` có sẵn.
- Burn phụ đề vào video bằng ffmpeg.
- Có thể chỉnh font size, style nền đen mờ hoặc viền chữ.
- Video xuất ra được lưu vào `exports/final/YYYYMMDD/`.

## Preset xuất

- `TikTok/Reels/Shorts`: `1080x1920`, `9:16`
- `YouTube`: `1920x1080`, `16:9`
- `Facebook Post`: `1080x1080`, `1:1`

## Test tạo ảnh

```bash
cd /Users/phuonganh/Desktop/BaoNgoc-MarketingStudio/hsk_marketing_studio
source venv/bin/activate
python scripts/test_vertex_image.py
```

## Test tạo video

```bash
cd /Users/phuonganh/Desktop/BaoNgoc-MarketingStudio/hsk_marketing_studio
source venv/bin/activate
python scripts/test_vertex_video.py
```

## Gợi ý VS Code

Nếu bạn mở workspace ở thư mục cha `BaoNgoc-MarketingStudio`, hãy cấu hình terminal mặc định mở ở `hsk_marketing_studio` để tránh nhầm với các file ở thư mục cha.

Tạo file `.vscode/settings.json` ở thư mục cha với nội dung:

```json
{
  "terminal.integrated.cwd": "/Users/phuonganh/Desktop/BaoNgoc-MarketingStudio/hsk_marketing_studio",
  "python.terminal.activateEnvironment": true
}
```

## Ghi chú

- Model name Vertex được cấu hình trong `config.yaml`.
- App ưu tiên `google.auth.default()` và chỉ dùng API key khi cần.
- Không hard-code secret.
- Không tự động generate khi mở app.
