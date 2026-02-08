@echo off
chcp 65001 >nul 2>&1
title YouTube 转录工具 - 环境配置

:: 切换到脚本目录
cd /d "%~dp0"

echo.
echo ==========================================
echo   正在配置环境，请稍候...
echo ==========================================
echo.

:: 使用 PowerShell 运行配置脚本
powershell -ExecutionPolicy Bypass -File "setup.ps1"

echo.
pause
