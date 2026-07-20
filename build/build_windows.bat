@echo off
REM Windows 打包成 SpringfieldPet.exe
REM 用法(在仓库根目录): build\build_windows.bat
cd /d "%~dp0\.."

echo ==^> 安装依赖
python -m pip install --upgrade pyinstaller PySide6

echo ==^> 清理旧产物
if exist build\work rmdir /s /q build\work
if exist dist\SpringfieldPet.exe del /q dist\SpringfieldPet.exe

echo ==^> PyInstaller 打包
pyinstaller build\springfield_pet.spec --distpath dist --workpath build\work --noconfirm

echo.
echo ==^> 完成: dist\SpringfieldPet.exe
pause
