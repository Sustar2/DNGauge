# Shotwell 参数对照（本项目）

来源文件：
- `/tmp/shotwell_src/src/photos/GRaw.vala`
- `/tmp/shotwell_src/src/photos/RawSupport.vala`
- `/tmp/shotwell_src/src/Dimensions.vala`
- `/tmp/shotwell_src/src/EditingHostPage.vala`
- `main.py` 中已移植的 Shotwell 色彩调整算法

## RAW 解码参数（rawpy.postprocess）
- `bright = 1.0`
- `half_size = false`（主查看固定 full-size 解码，保证放大范围与 Shotwell 单图查看一致）
- `highlight = CLIP`
- `use_auto_wb = true`
- `use_camera_wb = true`
- `use_camera_matrix = true`（best-effort 对齐 `EMBEDDED_COLOR_PROFILE`）
- `output_color = sRGB`
- `output_bps = 8`
- `user_flip = FROM_SOURCE`
- `user_qual = PPG`
- `no_auto_bright = true`
- `auto_bright_thr = 0.01`
- `gamma = (2.4, 12.92)`

## 缩放行为（按 Shotwell）
- 最大缩放：`2.0x`（200%）
- 最小缩放：`min(viewport/content, 1.0)`（适应窗口但不放大）
- 缩放曲线：`zoom = min * (max/min)^interp`
- 鼠标滚轮增量：`interp ± 0.1`
- 吸附：`interp < 0.03 -> 0`，`interp > 0.97 -> 1`

## 调整项（与 Shotwell 选项一致）
- Exposure
- Contrast
- Saturation
- Temperature
- Tint
- Highlights
- Shadows

滑杆范围：`[-100, +100]`，0 为默认；内部映射：
- Exposure/Contrast/Saturation/Temperature/Tint -> `[-16,+16]`
- Shadows -> `[0,+32]`
- Highlights -> `[-32,0]`

## 说明
- UI 栈不同（Shotwell: GTK；本项目: PyQt5），所以仍可能有细微显示差异。
- 但 RAW 参数、缩放上限/档位逻辑、调整算法均已对齐 Shotwell 关键逻辑。
