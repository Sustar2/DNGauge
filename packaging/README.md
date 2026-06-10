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
- `package_portable_linux.sh`
  - creates `../release/DNGauge-linux-portable`
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
```
