@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo Uso: arraste um arquivo de backup .db sobre este arquivo.
    pause
    exit /b 1
)
if not exist "%~1" (
    echo O arquivo de backup informado nao foi encontrado.
    pause
    exit /b 1
)

echo Feche o Sistema de Armarios antes de continuar.
choice /M "Restaurar este backup e substituir o banco atual"
if errorlevel 2 exit /b 0

if not exist "backups" mkdir "backups"
if exist "armarios.db" copy /Y "armarios.db" "backups\armarios_antes_da_restauracao.db" >nul
copy /Y "%~1" "armarios.db" >nul
if errorlevel 1 (
    echo Nao foi possivel restaurar o backup.
    pause
    exit /b 1
)
echo Backup restaurado com sucesso. Inicie o sistema novamente.
pause
