#!/usr/bin/env python3
"""
Build a Lambda deployment zip from the current project.

Usage:
    python scripts/build_lambda.py

Outputs:
    lambda_deployment.zip  (in project root)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
OUTPUT_ZIP = PROJECT_ROOT / "lambda_deployment.zip"
BUILD_DIR = PROJECT_ROOT / ".lambda_build"

# Dependencies not needed at runtime in Lambda
DEV_PACKAGES = {"pytest", "mypy", "ruff", "flask"}


def clean() -> None:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()


def install_deps() -> None:
    """Install production dependencies into the build directory."""
    req_file = PROJECT_ROOT / "requirements.txt"
    if not req_file.exists():
        print(f"ERROR: {req_file} not found")
        sys.exit(1)

    # Read requirements and drop dev packages
    lines = req_file.read_text().splitlines()
    filtered = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pkg_name = stripped.split("=")[0].split(">")[0].split("<")[0].strip().lower()
        if pkg_name not in DEV_PACKAGES:
            filtered.append(stripped)

    temp_req = BUILD_DIR / "_requirements.txt"
    temp_req.write_text("\n".join(filtered) + "\n")

    print(f"Installing {len(filtered)} production dependencies...")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "-r",
        str(temp_req),
        "-t",
        str(BUILD_DIR),
    ]

    # Lambda runs on Amazon Linux. If we are building on Windows, force
    # Linux-compatible wheels so the deployment package works in Lambda.
    if sys.platform == "win32":
        print("Detected Windows — forcing Linux (manylinux) wheels for Lambda compatibility...")
        cmd += [
            "--platform", "manylinux2014_x86_64",
            "--implementation", "cp",
            "--python-version", "3.12",
            "--only-binary", ":all:",
        ]

    subprocess.check_call(cmd)


def copy_source() -> None:
    """Copy application source and config into the build directory."""
    print("Copying source code...")
    src_dir = PROJECT_ROOT / "src"
    config_dir = PROJECT_ROOT / "config"

    if src_dir.exists():
        shutil.copytree(src_dir, BUILD_DIR / "src")
    if config_dir.exists():
        shutil.copytree(config_dir, BUILD_DIR / "config")


def strip_unnecessary_files() -> None:
    """Remove files not needed at runtime to keep package size down."""
    print("Stripping unnecessary files...")

    # ccxt async/pro — we only use sync API
    for path in (BUILD_DIR / "ccxt" / "async_support", BUILD_DIR / "ccxt" / "pro"):
        if path.exists():
            shutil.rmtree(path)
            print(f"  Removed {path.relative_to(BUILD_DIR)}")

    # Remove test directories from installed packages
    for pattern in ("test", "tests"):
        for path in list(BUILD_DIR.rglob(pattern)):
            if path.is_dir():
                shutil.rmtree(path)

    # Remove documentation and examples
    for pattern in ("docs", "doc", "examples", "benchmarks", "html"):
        for path in list(BUILD_DIR.rglob(pattern)):
            if path.is_dir():
                shutil.rmtree(path)

    # Remove stub files
    for path in list(BUILD_DIR.rglob("*.pyi")):
        path.unlink()

    # Remove Cython source files included in some wheels
    for path in list(BUILD_DIR.rglob("*.pyx")):
        path.unlink()

    # Remove __pycache__ and compiled Python files
    for pyc in list(BUILD_DIR.rglob("__pycache__")):
        if pyc.is_dir():
            shutil.rmtree(pyc)
    for pyc in list(BUILD_DIR.rglob("*.pyc")):
        pyc.unlink()

    # Strip debug symbols from .so files on Linux to reduce size
    if sys.platform != "win32":
        for so in BUILD_DIR.rglob("*.so"):
            try:
                subprocess.run(
                    ["strip", "--strip-debug", str(so)],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass


def create_zip() -> None:
    """Zip the build directory contents."""
    print(f"Creating {OUTPUT_ZIP.name}...")
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in BUILD_DIR.rglob("*"):
            if path.is_file():
                arcname = path.relative_to(BUILD_DIR)
                zf.write(path, arcname)

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"Done: {OUTPUT_ZIP.name} ({size_mb:.1f} MB)")
    if size_mb > 250:
        print("WARNING: Package exceeds Lambda's 250 MB unzipped limit!")
        sys.exit(1)


def main() -> None:
    clean()
    install_deps()
    copy_source()
    strip_unnecessary_files()
    create_zip()
    # Clean up build artifacts
    shutil.rmtree(BUILD_DIR)
    print("Build complete.")


if __name__ == "__main__":
    main()
