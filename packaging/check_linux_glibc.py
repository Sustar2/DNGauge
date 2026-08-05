#!/usr/bin/env python3
"""Fail when a PyInstaller executable requires a newer glibc than requested."""

import re
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


GLIBC_PATTERN = re.compile(rb"GLIBC_(\d+(?:\.\d+)*)")


def version_tuple(version):
    return tuple(int(part) for part in version.split("."))


def required_glibc(data):
    versions = {
        match.group(1).decode("ascii") for match in GLIBC_PATTERN.finditer(data)
    }
    return max(versions, key=version_tuple) if versions else None


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} PYINSTALLER_EXECUTABLE MAX_GLIBC", file=sys.stderr)
        return 2

    executable = Path(sys.argv[1])
    maximum = sys.argv[2]
    if not executable.is_file():
        print(f"Executable not found: {executable}", file=sys.stderr)
        return 2

    violations = []
    inspected = []

    outer_data = executable.read_bytes()
    outer_version = required_glibc(outer_data)
    if outer_version:
        inspected.append((str(executable), outer_version))

    archive = CArchiveReader(str(executable))
    for name, entry in archive.toc.items():
        if entry[-1] != "b":
            continue
        data = archive.extract(name)
        if not data or not data.startswith(b"\x7fELF"):
            continue

        version = required_glibc(data)
        if version:
            inspected.append((name, version))

    for name, version in inspected:
        if version_tuple(version) > version_tuple(maximum):
            violations.append((name, version))

    if not inspected:
        print("No ELF files with glibc requirements were found", file=sys.stderr)
        return 2

    highest_name, highest_version = max(
        inspected, key=lambda item: version_tuple(item[1])
    )
    print(f"Inspected {len(inspected)} ELF files")
    print(f"Highest required glibc: {highest_version} ({highest_name})")

    if violations:
        print(f"Found files requiring a newer glibc than {maximum}:", file=sys.stderr)
        for name, version in sorted(violations, key=lambda item: version_tuple(item[1])):
            print(f"  GLIBC_{version}: {name}", file=sys.stderr)
        return 1

    print(f"Compatibility check passed: all requirements are <= glibc {maximum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
