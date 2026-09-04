@echo off
REM Launches the widget with no console window.
REM
REM It uses the Windows "py launcher" instead of a bare `python`: that way it
REM does not matter that the Microsoft Store alias comes first in PATH.
REM
REM If anything fails, this script says so and waits: launched with `pyw` there
REM is no console to show an error in, and the window would close with no
REM explanation.

cd /d "%~dp0"

if not exist "main.py" (
    echo ERROR: cannot find main.py
    echo Current folder: %CD%
    echo This .bat has to sit next to main.py.
    goto :failed
)

where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: cannot find the Windows 'py' launcher.
    echo Install Python from python.org with "Add Python to PATH" checked,
    echo or start it by hand with:  pythonw main.py
    goto :failed
)

REM The check runs with `py`, NOT `pyw`: pythonw.exe is a GUI-subsystem app and
REM cmd.exe does not wait for it, so its errorlevel is useless for deciding
REM anything. `py` is a console app, so here it can be trusted.
REM
REM And it is a WARNING, not a barrier: a check with a false negative would
REM leave you unable to start the program at all. If it fails, it says so and
REM tries anyway.
py -3 -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo WARNING: could not verify PySide6. Details:
    echo.
    py -3 -c "import PySide6"
    echo.
    echo If the avatar does not show up, install it with:
    echo    py -3 -m pip install -r requirements.txt
    echo.
    pause
)

start "" pyw -3 main.py
exit /b 0

:failed
echo.
pause
exit /b 1
