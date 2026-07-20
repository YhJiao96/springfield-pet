#!/usr/bin/env bash
# macOS 打包成 SpringfieldPet.app
# 用法: bash build/build_macos.sh
set -e
cd "$(dirname "$0")/.."   # 到仓库根目录

echo "==> 安装依赖"
python3 -m pip install -q --upgrade pyinstaller PySide6

echo "==> 清理旧产物"
rm -rf build/work dist/SpringfieldPet dist/SpringfieldPet.app

echo "==> PyInstaller 打包"
pyinstaller build/springfield_pet.spec \
  --distpath dist \
  --workpath build/work \
  --noconfirm

echo ""
echo "==> 完成: dist/SpringfieldPet.app"
echo "首次运行(未签名)如被拦截,执行:"
echo "  xattr -dr com.apple.quarantine dist/SpringfieldPet.app"
echo "然后到 系统设置>隐私与安全性>辅助功能 勾选 SpringfieldPet 以启用「键入当前终端」"
