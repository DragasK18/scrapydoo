@echo off
cd /d "%~dp0"

echo ===================================================
echo 1. VERIFICANDO PYTHON
echo ===================================================
python --version >nul 2>&1

if %errorlevel% equ 0 (
    echo ¡Python ya esta instalado!
    set "PYTHON_EXE=python"
    goto instalar_dependencias
)

echo Python no fue encontrado. Descargando Python 3.12...
curl -o python_installer.exe https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe

echo.
echo Instalando Python de forma silenciosa (esto puede tardar unos minutos)...
start /wait python_installer.exe /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

echo Limpiando instalador temporal...
del python_installer.exe

:: Le indicamos la ruta exacta donde se acaba de instalar para no tener que reiniciar la consola
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"

:instalar_dependencias
echo.
echo ===================================================
echo 2. INSTALANDO DEPENDENCIAS DEL PROYECTO
echo ===================================================
:: Actualizamos pip primero para evitar advertencias de texto rojo
%PYTHON_EXE% -m pip install --upgrade pip
%PYTHON_EXE% -m pip install -r requirements.txt

echo.
echo ===================================================
echo ¡TODO LISTO! 
echo El sistema esta preparado. Ya puedes cerrar esta 
echo ventana y abrir tu aplicacion.
echo ===================================================
pause