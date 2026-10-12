@echo off
rem Construye dist\RebarFlow\RebarFlow.exe y dist\RebarFlow-Windows.zip en un Windows con Python 3.10+.
rem Uso: doble clic o "packaging\build_windows.bat" desde cualquier carpeta.
setlocal
cd /d "%~dp0\.."

python -m venv .build-venv || goto :error
call .build-venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -e ".[gui]" pyinstaller || goto :error

python packaging\make_icon.py || goto :error
pyinstaller --noconfirm --clean packaging\rebarflow.spec || goto :error

copy /y packaging\LEEME.txt dist\RebarFlow\LEEME.txt >nul
powershell -NoProfile -Command "Compress-Archive -Path 'dist\RebarFlow' -DestinationPath 'dist\RebarFlow-Windows.zip' -Force" || goto :error

echo.
echo Listo: dist\RebarFlow\RebarFlow.exe  y  dist\RebarFlow-Windows.zip
exit /b 0

:error
echo.
echo La construccion fallo.
exit /b 1
