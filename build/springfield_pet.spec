# -*- mode: python ; coding: utf-8 -*-
# 用法(在仓库根目录):pyinstaller build/springfield_pet.spec
import os
import sys

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))   # 仓库根目录

datas = [(os.path.join(ROOT, "assets", "pet_assets"), "pet_assets")]
hiddenimports = ["pet", "companion", "PySide6.QtMultimedia"]

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PySide6.QtWebEngineCore"],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == "darwin":
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name="SpringfieldPet", console=False,
        icon=os.path.join(SPECPATH, "icon.icns"),
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="SpringfieldPet")
    app = BUNDLE(
        coll,
        name="SpringfieldPet.app",
        icon=os.path.join(SPECPATH, "icon.icns"),
        bundle_identifier="dev.springfieldpet.app",
        info_plist={
            "LSUIElement": True,           # 桌宠:不在 Dock/程序切换器出现
            "NSHighResolutionCapable": True,
            "CFBundleName": "Springfield Pet",
            "CFBundleDisplayName": "Springfield Pet",
        },
    )
else:
    # Windows / Linux:单文件可执行
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="SpringfieldPet", console=False,
        icon=os.path.join(SPECPATH, "icon.ico"),
    )
