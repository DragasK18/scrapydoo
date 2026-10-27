@echo off
title Scrappy Doo - Arranque
cd /d "%~dp0"
echo ==============================================
echo   SCRAPPY DOO - servidor + tunel Cloudflare
echo ==============================================
echo.
set "CLOUDFLARED="
if exist "%~dp0cloudflared.exe" set "CLOUDFLARED=%~dp0cloudflared.exe"
if exist "%~dp0..\cloudflared.exe" set "CLOUDFLARED=%~dp0..\cloudflared.exe"
if not defined CLOUDFLARED (
    echo [ERROR] No encontre cloudflared.exe.
    echo   Ponlo en: D:\Proyectos\Comparador de precios
    echo   o dentro de esta misma carpeta.
    echo.
    pause
    exit /b 1
)
echo [1/2] Iniciando el servidor local...
start "Scrappy Doo - Servidor" cmd /k python app.py
echo [2/2] Esperando a que arranque (7 seg)...
timeout /t 7 /nobreak >nul
echo Abriendo el tunel de Cloudflare...
start "Scrappy Doo - Tunel Cloudflare" cmd /k "%CLOUDFLARED%" tunnel --url http://localhost:5000
echo.
echo ==============================================
echo  LISTO.
echo  La URL para compartir aparece en la ventana:
echo  "Scrappy Doo - Tunel Cloudflare"
echo  Sera algo como: https://xxxx.trycloudflare.com
echo.
echo  IMPORTANTE: no cierres ninguna de las 2 ventanas
echo  mientras quieras que otros puedan entrar.
echo ==============================================
echo.
pause
