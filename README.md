# DNGauge

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
├── packaging/            # Build scripts, icons, spec, portable assets
│   ├── DNGauge.png
│   ├── DNGauge.ico
│   ├── DNGauge.spec
│   ├── build_linux.sh
│   ├── build_windows.bat
│   ├── package_portable_linux.sh
│   └── portable_assets/
├── release/              # Generated portable output (ignored)
├── build/                # PyInstaller build cache (ignored)
├── dist/                 # Generated executable output (ignored)
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

## 4. Packaging

### Linux executable

Build:

```bash
chmod +x packaging/build_linux.sh
./packaging/build_linux.sh
```

Output:

```text
dist/DNGauge
```

This is a PyInstaller single-file executable.

Branding:
- window icon uses `DNGauge.png`
- desktop launcher icon uses `DNGauge.png`

### Windows executable

Build on Windows:

```cmd
packaging\build_windows.bat
```

Output:

```text
dist\DNGauge.exe
```

Branding:
- executable icon uses `DNGauge.ico`
- taskbar / app identity is set to `DNGauge`

### GitHub Actions

This repo includes a GitHub release workflow:

```text
.github/workflows/build-packages.yml
```

It packages files into `release/` and publishes the files from `release/` as the GitHub Release assets.

### GitHub Release

Recommended release flow:

1. commit all changes to `main`
2. create a version tag such as `v0.1.0`
3. push the tag
4. GitHub Actions will:
   - build Linux and Windows packages
   - place final archives into `release/`
   - create a GitHub Release automatically
   - attach the files found in `release/`

Example:

```bash
git tag -a v0.1.0 -m "DNGauge v0.1.0"
git push origin main --tags
```

### Linux runtime note

Some Linux desktops may still require system Qt/XCB libraries such as:

```text
libxcb-xinerama0
```

### Portable release layout

The release process is centered on the `release/` directory.

Typical final contents:

```text
release/
├── DNGauge-linux-portable.zip
└── DNGauge-windows-portable.zip
```

The Linux portable folder used to build the archive keeps only the files needed by end users:

```text
release/DNGauge-linux-portable/
├── DNGauge                  # Main executable
├── DNGauge.desktop          # Ready-to-use launcher with icon
├── DNGauge.png              # Icon used by launcher/window
├── DNGauge.desktop.template # Template for re-installing launcher
├── install_desktop_launcher.sh
├── README_RUN.txt
├── README_RUN_CN.txt
└── README_RUN_EN.txt
```

Windows release package:

```text
release/DNGauge-windows-portable/
├── DNGauge.exe
├── DNGauge.ico
├── README_RUN.txt
├── README_RUN_CN.txt
└── README_RUN_EN.txt
```

---

## 5. Supported Inputs

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

## 6. Display Pipeline

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

## 7. Main UI

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

## 8. Comparison Behavior

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

## 9. RAW Display and RAW Parameters

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

## 10. LOCATE / Data Sampling

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

## 11. Large Image Notes

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

## 12. FAQ

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

## 13. Development Notes

- Main program: `shotwell_compare.py`
- RAW mapping reference: `SHOTWELL_MAPPING.md`
- Standard image loading now intentionally follows Shotwell's `scaled_read()` idea
- When changing UI behavior, avoid breaking RAW decode / RAW sampling code paths
