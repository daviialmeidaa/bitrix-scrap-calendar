@echo off
setlocal
chcp 65001 >nul

cd /d "C:\Users\Supra\Documents\Automação de Testes - Davi IEBT\senff\bitrix-scrap-calendar" || exit /b 1

python -u main.py --all

exit /b %ERRORLEVEL%
