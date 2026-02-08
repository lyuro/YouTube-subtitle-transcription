@echo off
chcp 65001 >nul 2>&1
title YouTube 视频转录工具

:: 切换到脚本目录
cd /d "%~dp0"

:: 使用 PowerShell 运行主脚本
powershell -ExecutionPolicy Bypass -File "run.ps1" %*

pause
