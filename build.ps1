$ErrorActionPreference = "Stop"

uv run --group dev python -m nuitka `
  --standalone `
  --onefile `
  --assume-yes-for-downloads `
  --enable-console `
  --output-dir=dist `
  --output-filename=auto-nte.exe `
  auto_nte.py
