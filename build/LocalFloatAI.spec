# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

project = Path(SPECPATH).parent
app = project / "app"

llama_datas, llama_binaries, llama_hidden = collect_all("llama_cpp")
llama_hidden += collect_submodules("llama_cpp")

analysis = Analysis(
    [str(app / "main.py")],
    pathex=[str(project), str(app)],
    binaries=llama_binaries,
    datas=llama_datas,
    hiddenimports=llama_hidden + ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto"],
    excludes=["torch", "tensorflow", "gradio", "notebook"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="LocalFloatAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
