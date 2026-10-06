@echo off
rem Builds FolderTemplateMaker.exe (into the "dist" folder) on a Windows PC that has Python installed.
rem Most people don't need this: the ready-made program can be downloaded from GitHub (see README.md).
setlocal
cd /d "%~dp0"

set "PY=py -3"
%PY% --version >nul 2>&1 || set "PY=python"
%PY% --version >nul 2>&1 || (
    echo Python was not found. Install it from https://www.python.org/downloads/ first.
    pause
    exit /b 1
)

%PY% -m pip install --upgrade pyinstaller || goto :failed
%PY% packaging\build_exe.py || goto :failed

echo.
echo All done - your program is dist\FolderTemplateMaker.exe
pause
exit /b 0

:failed
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
