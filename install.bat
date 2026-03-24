@echo off
:: =============================================================================
:: AWP - Agent Workflow Protocol :: Installation Launcher (Windows)
:: Launches the PowerShell installation wizard
:: =============================================================================

echo.
echo   AWP - Agent Workflow Protocol
echo   Starting Installation Wizard...
echo.

:: Check if PowerShell is available
where powershell >nul 2>&1
if %ERRORLEVEL% neq 0 (
    where pwsh >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo ERROR: PowerShell is required but not found.
        echo Please install PowerShell from: https://github.com/PowerShell/PowerShell
        pause
        exit /b 1
    )
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
    goto :end
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"

:end
if %ERRORLEVEL% neq 0 (
    echo.
    echo Installation encountered an error. Please check the output above.
    pause
)
