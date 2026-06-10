# DNG_COMPARE

PyQt5 desktop tool for side-by-side comparison of `DNG / RAW / JPG / PNG / TIFF` images.

Current focus:
- dual/single image comparison
- synchronized zoom and pan
- Shotwell-like RAW display pipeline
- plain `.RAW` loading with manual geometry / Bayer / packing input
- RAW-only channel view and RAW parameter adjustment
- rendered value / RAW value sampling (`LOCATE`)

---

## 1. File Structure

```text
DNG_COMPARE/
├── shotwell_compare.py   # Main program
├── requirements.txt      # Python dependencies
├── run.sh                # Linux launcher for conda env dng_compare
├── SHOTWELL_MAPPING.md   # Shotwell parameter mapping notes
├── README.md             # This document
└── .gitignore
```

---

## 2. Environment Setup

### Method A: `venv`

#### Linux / macOS
```bash
cd DNG_COMPARE
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

#### Windows
```cmd
cd DNG_COMPARE
python3 -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

If `rawpy` install fails, try:

```bash
python -m pip install -U pip setuptools wheel
```

### Method B: `conda`

```bash
cd DNG_COMPARE
conda create -n dng_compare python=3.11 -y
conda activate dng_compare
pip install -r requirements.txt
```

Notes:
- `pidng` is required for the internal temporary-DNG pipeline used by plain `.RAW` preview.
- `run.sh` assumes a local conda environment named `dng_compare`.

---

## 3. Run

### Run directly
```bash
python shotwell_compare.py
```

### Run with launcher (`Linux`)
```bash
chmod +x run.sh
./run.sh
```

### Open files at startup
```bash
python shotwell_compare.py left.dng right.jpg
# or
./run.sh left.dng right.jpg
```

---

## 4. Supported Inputs

### Standard images
- `jpg`
- `jpeg`
- `png`
- `tif`
- `tiff`
- `bmp`
- `webp`

### RAW family
- camera RAW formats supported by `rawpy/libraw`
- `dng`
- plain `.raw`

### Plain `.RAW` behavior

If a `.RAW` file cannot be recognized by `rawpy/libraw`, the app will ask for:
- width
- height
- bit depth
- Bayer pattern: `RGGB / BGGR / GRBG / GBRG`
- packing: `u16 / u8 / mipi10 / mipi12`

Default dialog value:

```text
4096,3072,10,RGGB,u16
```

---

## 5. Display Pipeline

### Camera RAW / DNG
- decoded by `rawpy`
- follows the Shotwell-like RAW display path in this project

### Plain `.RAW`
- unpacked using the user-supplied geometry / Bayer / packing
- preview path prefers:
  - plain `RAW` -> temporary `DNG` -> `rawpy/libraw`
- fallback path:
  - manual demosaic + color matrix render

This is done so plain `.RAW` preview is closer to the visual result of:

```text
raw_to_dng(...) -> open generated DNG
```

### Standard images (`JPG / PNG / TIFF / ...`)
- now loaded closer to Shotwell logic
- prefers scaled decode for the current viewport instead of full-image decode first
- much better for very large images

Important:
- there is no hard app-level pixel limit now
- actual limit depends on memory, Qt image handling, and zoom level

---

## 6. Main UI

Top toolbar groups:

- **Input**: `L↥` / `R↥`
  - load left / right image
- **Layout**: `布局·单/双`, `同步·开/关`, `←`
  - hold `←` to overlay right image on top of left image
- **调参**: `调参·开/关`
  - opens the right-side adjustment panels
- **LOCATE**: `Locate·开/关`, `Value:显示(渲染)` / `Value:RAW`, `通道·...`
- **视图**: `100%`, `Fit`

Bottom status bar:
- shows rendered sample values
- or RAW-domain sample values
- reports left and right results side by side

---

## 7. Comparison Behavior

### Dual image mode
- left and right panes shown together
- zoom / pan can be synchronized
- images do **not** need to have the same size
- coordinate comparison is mapped proportionally between the two images

### Single image mode
- only left pane is visible
- useful when inspecting one large image in detail

### Overlay peek
- hold `←`
- right image is temporarily shown over the left pane
- release to restore normal view

---

## 8. RAW Display and RAW Parameters

There are two RAW-related controls:

### `通道·ALL / R / G1 / G2 / B`
- switches RAW channel view
- `ALL` shows the rendered image
- `R / G1 / G2 / B` show Bayer-domain channel visualization

### `RAW 调参`
- per-pane controls
- available parameters:
  - channel
  - display bit
  - black level
  - white level
  - exposure gain
  - white balance enable
  - `WB R / G / B`

RAW-only rule:
- these controls only apply to true editable plain-RAW panes
- if a pane loads `DNG`, `JPG`, `PNG`, or other non-plain-RAW content, that pane's RAW controls are disabled

Disabled hint examples:
- `DNG 不支持 RAW 调参`
- `JPG 不支持 RAW 调参`
- `PNG 不支持 RAW 调参`

If left is plain `.RAW` and right is `DNG`:
- left RAW controls work
- right RAW controls are disabled
- top `通道` button only acts on the available RAW pane

---

## 9. LOCATE / Data Sampling

### Rendered-value mode
Button:

```text
Value:显示(渲染)
```

Clicking the image reports:
- rendered `R/G/B`
- grayscale value
- mapped left/right positions

If RAW data exists, rendered mode also appends RAW-domain info for that point.

### RAW-value mode
Button:

```text
Value:RAW
```

Reports:
- RAW-domain coordinate
- RAW original value
- RAW channel identity
- dtype

For channel mode:
- `ALL` samples the RAW value at the mapped pixel
- `R/G1/G2/B` samples the nearest valid pixel in that Bayer channel

---

## 10. Large Image Notes

### Why Shotwell opened some large JPG/PNG faster

Shotwell does not always fully decode the whole standard image first.
This project now follows the same high-level idea:
- decode standard images near the current viewport size
- use a special downsample path for very large source images and very small target display sizes

### Remaining practical limits

Very large images may still become slow when:
- switching to `100%`
- repeatedly zooming into full resolution
- opening two very large images at once
- running on limited RAM / VRAM

---

## 11. FAQ

### Q1: Why is plain `.RAW` different from camera RAW / DNG?

Because plain `.RAW` has no complete metadata container by itself.
The app needs user input for geometry / Bayer / packing, and then builds a preview pipeline from that.

### Q2: Why can `JPG` or `PNG` show “not support RAW adjust”?

Because RAW adjust is only for the plain-RAW parameter pipeline, not for already-rendered images.

### Q3: Do left and right images need the same size?

No.
Different sizes are supported.
Comparison and sampling use proportional coordinate mapping.

### Q4: Why can a huge JPG still feel slow?

Although standard-image loading now uses scaled decode, `100%` display and repeated large-image interaction can still be expensive.

---

## 12. Development Notes

- Main program: `shotwell_compare.py`
- RAW mapping reference: `SHOTWELL_MAPPING.md`
- Standard image loading now intentionally follows Shotwell's `scaled_read()` idea
- When changing UI behavior, avoid breaking RAW decode / RAW sampling code paths

