DNGauge Windows Portable
========================

1. What is included
-------------------

- `DNGauge.exe` : main executable
- `DNGauge.ico` : application icon
- `README_RUN.txt` : quick entry guide
- `README_RUN_CN.txt` : Chinese guide
- `README_RUN_EN.txt` : English guide

2. How to run
-------------

1. Extract the whole folder.
2. Keep all files in the same directory.
3. Double-click `DNGauge.exe`.

3. Supported inputs
-------------------

- Standard images: `jpg`, `jpeg`, `png`, `tif`, `tiff`, `bmp`, `webp`
- Camera RAW formats supported by `rawpy/libraw`
- `dng`
- Plain `.raw`

4. Main features
----------------

- left/right image comparison
- synchronized zoom and pan
- mixed RAW / DNG / JPG / PNG comparison
- `Value:显示(渲染)` and `Value:RAW` sampling
- plain `.RAW` manual metadata input and RAW adjustment

5. Usage guide
--------------

Top toolbar:

- `L↥` : load image into the left pane
- `R↥` : load image into the right pane
- `布局·单/双` : switch between single-pane and dual-pane layout
- `同步·开/关` : enable or disable synchronized zoom / pan
- `←` : hold to overlay the right image on top of the left image
- `调参·开/关` : show or hide the adjustment panels
- `Locate·开/关` : enable click-to-sample mode
- `Value:显示(渲染)` : sample rendered RGB / gray values
- `Value:RAW` : sample RAW-domain values when RAW data is available
- `通道·ALL / R / G1 / G2 / B` : switch RAW channel view
- `100%` : jump to 1:1 display
- `Fit` : fit the image to the viewport

Right-side adjustment panels:

- image adjustment panel:
  exposure, contrast, saturation, temperature, tint, highlights, shadows
- `重置` : reset the current image adjustment sliders

RAW adjustment panel:

- channel
- display bit
- black level
- white level
- exposure gain
- white balance enable
- `WB R / G / B`

Comparison and sampling:

- left and right images can have different sizes
- comparison uses proportional coordinate mapping
- bottom info bar shows left/right sample results
- `Value:RAW` shows RAW value, coordinate, channel, and dtype
- `Value:显示(渲染)` shows rendered RGB / gray values

RAW notes:

- RAW-only controls work only for editable plain `.RAW` panes
- if a pane contains `DNG`, `JPG`, `PNG`, or another non-plain-RAW image, RAW controls for that pane are disabled
- plain `.RAW` that cannot be recognized automatically will ask for:
  width, height, bit depth, Bayer pattern, and packing format

6. Notes
--------

- no separate Python environment is required
- if Windows SmartScreen shows a warning, review it before running
- keep the whole folder together; do not move only `DNGauge.exe`
