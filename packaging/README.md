# Packaging

This folder contains all build and distribution assets for `DNGauge`.

## Files

- `DNGauge.spec`
  - PyInstaller spec
- `DNGauge.png`
  - Linux icon
- `DNGauge.ico`
  - Windows icon
- `build_linux.sh`
  - builds `../dist/DNGauge`
- `build_windows.bat`
  - builds `..\dist\DNGauge.exe`
- `check_plain_raw_pipeline.py`
  - verifies that PiDNG and the plain-RAW temporary-DNG render path work on the build platform
- `package_portable_linux.sh`
  - creates `../release/DNGauge-linux-portable`
- `package_windows_portable.bat`
  - creates `..\release\DNGauge-windows-portable`
- `portable_assets/`
  - launcher template and end-user readmes

## Typical workflow

Linux:

```bash
./packaging/build_linux.sh
./packaging/package_portable_linux.sh
```

Windows:

```cmd
packaging\build_windows.bat
packaging\package_windows_portable.bat
```
