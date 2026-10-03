import os
import sys
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent  # noqa: F821 -- PyInstaller supplies this path.
datas = collect_data_files("terminx")
for distribution in (
    "terminx",
    "rich",
    "psutil",
    "PySide6",
    "PySide6_Essentials",
    "PySide6_Addons",
    "shiboken6",
    "tomlkit",
    "markdown-it-py",
    "mdurl",
    "Pygments",
):
    datas += copy_metadata(distribution)

analysis = Analysis(
    [str(root / "packaging" / "entry.py")],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=[
        "terminx.bridge",
        "terminx.launch",
        "terminx.core.console_identity",
        "terminx.core.runtime",
    ],
    excludes=[
        "tkinter",
        "numpy",
        "matplotlib",
        "pytest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
    ],
)
allowed_roots = (
    Path(sys.prefix).resolve(),
    Path(sys.base_prefix).resolve(),
    Path(os.environ["SystemRoot"]).resolve(),
)
allowed_qt = {
    "qt6core.dll",
    "qt6gui.dll",
    "qt6network.dll",
    "qt6widgets.dll",
    "qt6opengl.dll",
    "qt6svg.dll",
}
selected = []
for destination, source, kind in analysis.binaries:
    origin = Path(source).resolve()
    if not any(origin.is_relative_to(directory) for directory in allowed_roots):
        raise RuntimeError(f"A binary is outside the release environment: {origin}")
    name = Path(destination).name.casefold()
    if name.startswith("qt6") and name.endswith(".dll") and name not in allowed_qt:
        continue
    if name in {"qtvirtualkeyboardplugin.dll", "qpdf.dll", "pyside6qml.abi3.dll"}:
        continue
    # Windows supplies the ICU ABI expected by Qt. A Conda ICU is incompatible.
    if name == "icuuc.dll" or name.startswith("icudt"):
        continue
    selected.append((destination, source, kind))
analysis.binaries = selected
archive = PYZ(analysis.pure)
console = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="terminx",
    console=True,
    upx=False,
)
sidebar = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="terminx-sidebar",
    console=False,
    upx=False,
)
COLLECT(
    console,
    sidebar,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="terminx",
)
