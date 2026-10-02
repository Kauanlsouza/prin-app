@echo off
setlocal
cd /d "%~dp0"

echo Iniciando o Sistema de Armarios...
echo Mantenha esta janela aberta enquanto o sistema estiver em uso.
start "Sistema de Armarios" /B py -3 app.py
timeout /t 2 /nobreak >nul
start "" http://localhost:5000

echo.
echo O sistema foi aberto no navegador em http://localhost:5000
echo Para encerrar, feche esta janela ou pressione Ctrl+C.
pause >nul
