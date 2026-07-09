@echo off
setlocal

set ENV_NAME=vibecoding

if not defined CONDA_EXE (
  for %%C in (
    "%USERPROFILE%\miniconda3\Scripts\conda.exe"
    "%USERPROFILE%\anaconda3\Scripts\conda.exe"
    "C:\ProgramData\miniconda3\Scripts\conda.exe"
    "C:\ProgramData\anaconda3\Scripts\conda.exe"
    "D:\anaconda3\Scripts\conda.exe"
  ) do (
    if exist %%~C set "CONDA_EXE=%%~C"
  )
)

if not defined CONDA_EXE (
  for /f "delims=" %%C in ('where conda 2^>nul') do (
    if not defined CONDA_EXE set "CONDA_EXE=%%C"
  )
)

if not defined CONDA_EXE (
  echo Could not find conda.exe.
  echo Run install_env.bat first, add conda to PATH, or set CONDA_EXE before running this script.
  pause
  exit /b 1
)

cd /d "%~dp0"
"%CONDA_EXE%" run -n %ENV_NAME% python transcript.py
