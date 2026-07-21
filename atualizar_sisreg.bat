@echo off
title SISREG - Atualizacao Automatica

if "%1"=="-run" goto :inicio
cmd /k "%~f0" -run
exit

:inicio
echo ============================================================
echo   SISREG - Atualizacao Automatica de Dados
echo ============================================================
echo.

cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

:: 1. PENDENTES SGO
echo [1/3] Exportando Demanda Reprimida SGO...
python sisreg_pendentes_sgo.py
if %errorlevel% neq 0 (
    echo     ERRO ao exportar pendentes SGO. Continuando...
) else (
    echo     OK - Pendentes SGO exportados.
)
echo.

:: 2. AGENDAMENTOS
echo [2/3] Exportando Agendamentos...
python sisreg_agendamentos.py
if %errorlevel% neq 0 (
    echo     ERRO ao exportar agendamentos. Continuando...
) else (
    echo     OK - Agendamentos exportados.
)
echo.

:: 3. OFERTA DE VAGAS
echo [3/3] Exportando Oferta de Vagas...
python sisreg_oferta.py
if %errorlevel% neq 0 (
    echo     ERRO ao exportar oferta. Continuando...
) else (
    echo     OK - Oferta exportada.
)
echo.

:: GIT
echo ============================================================
echo   Enviando dados para o GitHub...
echo ============================================================

git add "Agendamento" "Demanda_Reprimida_SGO" "Oferta"
git status --short

set DT=%date:/=-%
set TM=%time::=-%
set TM=%TM: =0%
git commit -m "Atualizacao automatica - %DT% %TM%"
if %errorlevel% neq 0 (
    echo     Nenhuma alteracao para commitar.
) else (
    git push
    if %errorlevel% neq 0 (
        echo     ERRO ao enviar para o GitHub. Verifique a conexao.
    ) else (
        echo     OK - Dados enviados ao GitHub.
    )
)

echo.
echo ============================================================
echo   Concluido! O painel sera atualizado em instantes.
echo ============================================================
echo.
pause
goto :eof