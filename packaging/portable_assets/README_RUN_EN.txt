DNGauge Linux Portable
======================

1. What is included
-------------------

- `DNGauge` : main executable
- `DNGauge.desktop` : in-folder launcher with icon
- `DNGauge.png` : app icon / desktop icon
- `install_desktop_launcher.sh` : install desktop/app-menu shortcut
- `DNGauge.desktop.template` : template used by the installer

2. How to run
-------------

Recommended:
1. Extract the whole folder.
2. Keep all files in the same directory.
3. Double-click `DNGauge.desktop`.

You can also:
- double-click `DNGauge`

Alternative:
- run `./DNGauge`

Desktop integration:
1. Run `./install_desktop_launcher.sh`
2. Open `DNGauge` from the desktop or app menu

3. Supported inputs
-------------------

- Standard images: `jpg`, `jpeg`, `png`, `tif`, `tiff`, `bmp`, `webp`
- Camera RAW formats supported by `rawpy/libraw`
- `dng`
- Plain `.raw`

4. Main buttons
---------------

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

5. Comparison and sampling
--------------------------

- left and right images can have different sizes
- comparison uses proportional coordinate mapping
- bottom info bar shows left/right sample results
- `Value:RAW` shows RAW value, coordinate, channel, and dtype
- `Value:显示(渲染)` shows rendered RGB / gray values

6. RAW notes
------------

- RAW-only controls work only for editable plain `.RAW` panes
- if a pane contains `DNG`, `JPG`, `PNG`, or another non-plain-RAW image, RAW controls for that pane are disabled
- plain `.RAW` that cannot be recognized automatically will ask for:
  width, height, bit depth, Bayer pattern, and packing format

7. Notes
--------

- no Python / conda environment is required
- keep the whole portable folder together
- if your Linux file manager blocks `.desktop` launchers, use the `DNGauge` executable directly
- after desktop integration, the app menu and desktop shortcut use `DNGauge.png` as the icon
