@echo off
rem Windows: run Momentum with one command (installs what it needs, then opens the browser).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\dev.ps1" start %*
