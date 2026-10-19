@echo off
chcp 65001 >nul
rem Statue Maker: bir .glb / .gltf / .fbx / .obj / .blend / Sketchfab .zip dosyasini bu dosyanin uzerine surukle-birak.
rem Cikti: out\<Ad>\ klasoru (model.statue, dokular, statue.json, icon.png, license.txt).
rem Ikinci parametre "install" ise klasor UserData\StatueShop\ icine de kopyalanir.
cd /d "%~dp0"
if "%~1"=="" (
  echo Kullanim: modeli ^(.glb / .gltf / .fbx / .zip^) bu dosyanin uzerine surukle-birak.
  echo           ya da: StatueMaker.bat model.glb install
  pause
  exit /b
)
set INST=
if /i "%~2"=="install" set INST=--install
python statuemaker.py "%~1" --form %INST%
if errorlevel 1 (
  echo.
  echo HATA. Yukaridaki mesajlari Claude'a gonder.
) else (
  echo.
  echo TAMAM. Klasor: %~dp0out
  explorer "%~dp0out"
)
pause
