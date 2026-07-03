@echo off
cd /d "%~dp0"
echo Iniciando Agentes de IA en la Nube - Deportes...
start "Servidor - Agentes IA Deportes" py -m uvicorn main:app --host 0.0.0.0 --port 8011
timeout /t 3 /nobreak >nul
start "" http://localhost:8011
echo.
echo ==========================================================
echo  Para abrirla en tu celular Android:
echo  1. Conecta el celular a la MISMA red WiFi que esta PC.
echo  2. Abre el navegador del celular y visita la direccion IPv4 de abajo, seguida de :8011
echo.
ipconfig | findstr /c:"IPv4"
echo.
echo  Ejemplo: http://192.168.100.18:8011
echo  Si Windows pregunta por el Firewall, elige "Permitir acceso".
echo ==========================================================
echo.
pause
