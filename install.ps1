# =============================================================================
# AWP - Agent Workflow Protocol :: Installation Script (Windows PowerShell)
# Creates: ~/.awp/ with venv, global .env config, and 'awp' CLI on PATH
# =============================================================================

#Requires -Version 5.1
$ErrorActionPreference = "Stop"

# -- Colors & helpers ---------------------------------------------------------

function Write-Info    { param($msg) Write-Host "[INFO] " -ForegroundColor Blue -NoNewline; Write-Host $msg }
function Write-Success { param($msg) Write-Host "[OK] " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Write-Warn    { param($msg) Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Write-Err     { param($msg) Write-Host "[ERROR] " -ForegroundColor Red -NoNewline; Write-Host $msg }

function Write-Banner {
    Write-Host ""
    Write-Host "    ___  _      ______" -ForegroundColor Cyan
    Write-Host "   /   || | /| / / __ \" -ForegroundColor Cyan
    Write-Host "  / /| || |/ |/ / /_/ /" -ForegroundColor Cyan
    Write-Host " / ___ ||__/|__/ ____/" -ForegroundColor Cyan
    Write-Host "/_/  |_|       /_/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Agent Workflow Protocol" -ForegroundColor Cyan
    Write-Host "  Installation Wizard" -ForegroundColor Cyan
    Write-Host ""
}

$AWP_HOME = Join-Path $env:USERPROFILE ".awp"
$AWP_VENV = Join-Path $AWP_HOME "venv"
$AWP_ENV  = Join-Path $AWP_HOME ".env"
$AWP_BIN  = Join-Path $AWP_HOME "bin"
$SCRIPT_DIR = $PSScriptRoot
$MIN_PYTHON_VERSION = [version]"3.10"

# -- Step 1: System checks ----------------------------------------------------

function Test-PythonVersion {
    Write-Info "Checking Python version..."

    $pythonCmds = @("python", "python3", "py")
    $pythonCmd = $null

    foreach ($cmd in $pythonCmds) {
        try {
            $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver) {
                $parsed = [version]$ver
                if ($parsed -ge $MIN_PYTHON_VERSION) {
                    $pythonCmd = $cmd
                    Write-Success "Found $cmd ($ver)"
                    break
                }
            }
        } catch { }
    }

    if (-not $pythonCmd) {
        Write-Err "Python >= $MIN_PYTHON_VERSION is required but not found."
        Write-Host ""
        Write-Host "Install Python from: https://www.python.org/downloads/"
        Write-Host "IMPORTANT: Check 'Add Python to PATH' during installation."
        exit 1
    }

    return $pythonCmd
}

function Test-Git {
    Write-Info "Checking git..."
    try {
        $gitVer = git --version 2>$null
        if ($gitVer) {
            Write-Success "git available ($gitVer)"
            return
        }
    } catch { }

    Write-Warn "git not found."
    Write-Host "Install git from: https://git-scm.com/download/win"
    Write-Host "Or run: winget install Git.Git"
    $install = Read-Host "Try installing with winget now? [Y/n]"
    if ($install -ne "n") {
        try {
            winget install Git.Git --accept-package-agreements --accept-source-agreements
            Write-Success "git installed (restart terminal to use)"
        } catch {
            Write-Err "Could not install git automatically. Please install manually."
            exit 1
        }
    }
}

function Test-Ollama {
    Write-Info "Checking Ollama..."
    $script:OllamaInstalled = $false

    try {
        $null = Get-Command ollama -ErrorAction Stop
        Write-Success "Ollama available"
        $script:OllamaInstalled = $true
    } catch {
        Write-Host ""
        Write-Host "Ollama is not installed." -ForegroundColor Yellow
        Write-Host "Ollama provides cloud and local LLM inference."
        Write-Host ""
        $install = Read-Host "Install Ollama now? [Y/n]"
        if ($install -ne "n") {
            Write-Info "Installing Ollama..."
            try {
                winget install Ollama.Ollama --accept-package-agreements --accept-source-agreements
                Write-Success "Ollama installed (may require restart)"
                $script:OllamaInstalled = $true
            } catch {
                Write-Warn "Could not install Ollama. Download from: https://ollama.com/download"
            }
        } else {
            Write-Info "Skipping Ollama installation"
        }
    }
}

# -- Step 2: Create AWP home --------------------------------------------------

function Initialize-AwpHome {
    Write-Info "Setting up AWP home directory at $AWP_HOME..."
    New-Item -ItemType Directory -Path $AWP_HOME -Force | Out-Null
    New-Item -ItemType Directory -Path $AWP_BIN -Force | Out-Null
    Write-Success "AWP home ready: $AWP_HOME"
}

# -- Step 3: Virtual environment -----------------------------------------------

function Initialize-Venv {
    param($PythonCmd)

    if (Test-Path $AWP_VENV) {
        Write-Info "Existing venv found at $AWP_VENV"
        $recreate = Read-Host "Recreate virtual environment? [y/N]"
        if ($recreate -eq "y") {
            Remove-Item -Recurse -Force $AWP_VENV
        } else {
            Write-Info "Reusing existing venv"
            return
        }
    }

    Write-Info "Creating virtual environment..."
    & $PythonCmd -m venv $AWP_VENV
    Write-Success "Virtual environment created"
}

# -- Step 4: Install AWP package -----------------------------------------------

function Install-Awp {
    $pip = Join-Path $AWP_VENV "Scripts\pip.exe"

    Write-Info "Upgrading pip..."
    & $pip install --upgrade pip setuptools wheel -q 2>$null

    Write-Info "Installing AWP Protocol..."

    # Try PyPI first
    $pypiResult = & $pip install awp-protocol -q 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Installed awp-protocol from PyPI"
    } else {
        $localToml = Join-Path $SCRIPT_DIR "reference\python\pyproject.toml"
        if (Test-Path $localToml) {
            Write-Info "PyPI package not found. Installing from local source..."
            $localPath = Join-Path $SCRIPT_DIR "reference\python"
            & $pip install -e $localPath -q
            Write-Success "Installed awp-protocol from local source"
        } else {
            Write-Info "Installing from GitHub..."
            & $pip install "git+https://github.com/veegee82/agent-workflow-protocol.git#subdirectory=reference/python" -q
            Write-Success "Installed awp-protocol from GitHub"
        }
    }

    # Install common workflow dependencies
    Write-Info "Installing common workflow dependencies..."
    & $pip install ddgs httpx -q 2>$null

    # Verify
    $awpExe = Join-Path $AWP_VENV "Scripts\awp.exe"
    if (Test-Path $awpExe) {
        Write-Success "AWP CLI verified"
    } else {
        Write-Err "AWP CLI installation failed"
        exit 1
    }
}

# -- Step 5: Create CLI wrapper ------------------------------------------------

function New-CliWrapper {
    Write-Info "Creating AWP CLI wrappers..."

    # PowerShell wrapper
    $ps1Wrapper = Join-Path $AWP_BIN "awp.ps1"
    @"
# AWP CLI wrapper -- loads global config and runs awp
`$awpHome = Join-Path `$env:USERPROFILE ".awp"
`$awpEnv  = Join-Path `$awpHome ".env"
`$awpExe  = Join-Path `$awpHome "venv\Scripts\awp.exe"

# Load global .env
if (Test-Path `$awpEnv) {
    Get-Content `$awpEnv | ForEach-Object {
        `$line = `$_.Trim()
        if (`$line -and -not `$line.StartsWith("#") -and `$line.Contains("=")) {
            `$parts = `$line.Split("=", 2)
            `$key = `$parts[0].Trim()
            `$val = `$parts[1].Trim().Trim("'`"")
            if (`$key -and `$val) {
                [Environment]::SetEnvironmentVariable(`$key, `$val, "Process")
            }
        }
    }
}

& `$awpExe @args
"@ | Set-Content -Path $ps1Wrapper -Encoding UTF8

    # CMD wrapper (.cmd for Command Prompt compatibility)
    $cmdWrapper = Join-Path $AWP_BIN "awp.cmd"
    @"
@echo off
setlocal enabledelayedexpansion

set "AWP_HOME=%USERPROFILE%\.awp"
set "AWP_ENV=%AWP_HOME%\.env"
set "AWP_EXE=%AWP_HOME%\venv\Scripts\awp.exe"

:: Load global .env
if exist "%AWP_ENV%" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%AWP_ENV%") do (
        set "line=%%a"
        if not "!line:~0,1!"=="#" (
            set "%%a=%%b"
        )
    )
)

"%AWP_EXE%" %*
"@ | Set-Content -Path $cmdWrapper -Encoding ASCII

    Write-Success "CLI wrappers created"
}

# -- Step 6: Add to PATH ------------------------------------------------------

function Add-ToPath {
    Write-Info "Configuring PATH..."

    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($userPath -like "*$AWP_BIN*") {
        Write-Info "PATH already configured"
    } else {
        [Environment]::SetEnvironmentVariable("PATH", "$AWP_BIN;$userPath", "User")
        $env:PATH = "$AWP_BIN;$env:PATH"
        Write-Success "Added $AWP_BIN to user PATH"
    }

    # Also set PowerShell profile alias
    $profileDir = Split-Path $PROFILE -Parent
    if (-not (Test-Path $profileDir)) {
        New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
    }

    if (-not (Test-Path $PROFILE)) {
        New-Item -ItemType File -Path $PROFILE -Force | Out-Null
    }

    $profileContent = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
    if (-not $profileContent -or $profileContent -notlike "*awp.ps1*") {
        Add-Content -Path $PROFILE -Value "`n# AWP - Agent Workflow Protocol"
        Add-Content -Path $PROFILE -Value "Set-Alias -Name awp -Value `"$AWP_BIN\awp.ps1`""
        Write-Success "Added awp alias to PowerShell profile"
    }
}

# -- Step 7: Setup Wizard (LLM Configuration) ---------------------------------

function Start-SetupWizard {
    Write-Host ""
    Write-Host "=== LLM Provider Configuration ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "AWP needs an LLM provider to run agent workflows."
    Write-Host "You can change these settings later by editing: $AWP_ENV"
    Write-Host ""
    Write-Host "Available providers:"
    Write-Host "  1) OpenRouter  (cloud, free tier available, recommended)"
    Write-Host "  2) Ollama      (cloud & local, uses cloud models by default)"
    Write-Host "  3) OpenAI      (cloud, requires paid API key)"
    Write-Host "  4) Groq        (cloud, free tier available)"
    Write-Host "  5) Together    (cloud, free tier available)"
    Write-Host "  6) Custom      (any OpenAI-compatible endpoint)"
    Write-Host "  7) Skip        (configure later)"
    Write-Host ""

    $choice = Read-Host "Select PRIMARY LLM provider [1]"
    if (-not $choice) { $choice = "1" }

    $config = @{
        Primary         = ""
        Fallback        = "ollama"
        Vision          = "ollama"
        OpenRouterKey   = ""
        OllamaBaseUrl   = "https://ollama.com"
        OllamaModel     = "nemotron-3-super:cloud"
        OpenAIKey       = ""
        GroqKey         = ""
        TogetherKey     = ""
        CustomUrl       = ""
        CustomKey       = ""
        CustomModel     = ""
        Model           = ""
    }

    switch ($choice) {
        "1" {
            $config.Primary = "openrouter"
            Write-Host ""
            Write-Host "OpenRouter Configuration:" -ForegroundColor Cyan
            Write-Host "  Get a free API key at: https://openrouter.ai/keys"
            Write-Host ""
            $config.OpenRouterKey = Read-Host "OpenRouter API key"
            $model = Read-Host "Model [openai/gpt-5-nano]"
            if (-not $model) { $model = "openai/gpt-5-nano" }
            $config.Model = $model
        }
        "2" {
            $config.Primary = "ollama"
            Write-Host ""
            Write-Host "Ollama Configuration:" -ForegroundColor Cyan
            Write-Host "  Ollama uses cloud models by default for best performance."
            Write-Host "  Use ':cloud' suffix for cloud inference, or plain name for local."
            Write-Host ""
            $url = Read-Host "Ollama base URL [https://ollama.com]"
            if ($url) { $config.OllamaBaseUrl = $url } else { $config.OllamaBaseUrl = "https://ollama.com" }
            $model = Read-Host "Model [nemotron-3-super:cloud]"
            if ($model) { $config.OllamaModel = $model; $config.Model = $model }
            else { $config.OllamaModel = "nemotron-3-super:cloud"; $config.Model = "nemotron-3-super:cloud" }
        }
        "3" {
            $config.Primary = "openai"
            Write-Host ""
            Write-Host "OpenAI Configuration:" -ForegroundColor Cyan
            $config.OpenAIKey = Read-Host "OpenAI API key"
            $model = Read-Host "Model [gpt-4o]"
            if (-not $model) { $model = "gpt-4o" }
            $config.Model = $model
        }
        "4" {
            $config.Primary = "groq"
            Write-Host ""
            Write-Host "Groq Configuration:" -ForegroundColor Cyan
            Write-Host "  Get a free API key at: https://console.groq.com/keys"
            $config.GroqKey = Read-Host "Groq API key"
            $model = Read-Host "Model [llama-3.3-70b-versatile]"
            if (-not $model) { $model = "llama-3.3-70b-versatile" }
            $config.Model = $model
        }
        "5" {
            $config.Primary = "together"
            Write-Host ""
            Write-Host "Together Configuration:" -ForegroundColor Cyan
            $config.TogetherKey = Read-Host "Together API key"
            $model = Read-Host "Model [meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo]"
            if (-not $model) { $model = "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo" }
            $config.Model = $model
        }
        "6" {
            $config.Primary = "custom"
            Write-Host ""
            Write-Host "Custom Provider Configuration:" -ForegroundColor Cyan
            $config.CustomUrl = Read-Host "Base URL (OpenAI-compatible)"
            $config.CustomKey = Read-Host "API key (leave empty if none)"
            $config.CustomModel = Read-Host "Model name"
            $config.Model = $config.CustomModel
        }
        "7" {
            Write-Warn "Skipping LLM configuration. Edit $AWP_ENV later."
            Write-MinimalEnv
            return
        }
        default {
            $config.Primary = "openrouter"
            $config.Model = "openai/gpt-5-nano"
        }
    }

    # Fallback
    Write-Host ""
    Write-Host "Fallback provider (used when primary is unavailable):" -ForegroundColor Cyan
    if ($config.Primary -eq "openrouter") {
        $fb = Read-Host "Use Ollama as fallback? [Y/n]"
        if ($fb -eq "n") { $config.Fallback = "none" }
    } elseif ($config.Primary -eq "ollama") {
        $fb = Read-Host "Use OpenRouter as fallback? [Y/n]"
        if ($fb -ne "n") {
            $config.Fallback = "openrouter"
            if (-not $config.OpenRouterKey) {
                $config.OpenRouterKey = Read-Host "OpenRouter API key (get free at openrouter.ai)"
            }
        }
    }

    # Vision
    Write-Host ""
    Write-Host "Vision provider (for image processing tasks):" -ForegroundColor Cyan
    Write-Host "  Cloud-first: uses cloud vision models by default."
    Write-Host "  Options: ollama (cloud), openrouter, openai"
    $vis = Read-Host "Vision provider [ollama]"
    if ($vis) { $config.Vision = $vis }

    Write-EnvFile $config

    # Pull Ollama models
    if ($script:OllamaInstalled -and ($config.Primary -eq "ollama" -or $config.Fallback -eq "ollama")) {
        Write-Host ""
        $pull = Read-Host "Pull Ollama models now? (requires Ollama running) [Y/n]"
        if ($pull -ne "n") {
            try {
                $modelToPull = if ($config.Primary -eq "ollama") { $config.OllamaModel } else { "nemotron-3-super:cloud" }
                Write-Info "Pulling model: $modelToPull (this may take a while)..."
                & ollama pull $modelToPull
            } catch {
                Write-Warn "Could not pull model. Pull it later with: ollama pull $modelToPull"
            }
        }
    }
}

function Write-EnvFile {
    param($Config)

    Write-Info "Writing global configuration to $AWP_ENV..."

    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss") + " UTC"
    $lines = @(
        "# ============================================================================="
        "# AWP - Agent Workflow Protocol :: Global Configuration"
        "# Generated by install.ps1 on $timestamp"
        "#"
        "# This file provides FALLBACK values for LLM configuration."
        "# Workflow-level secrets.yaml and .env files take precedence."
        "# ============================================================================="
        ""
        "# --- LLM Provider Selection ---"
        "LLM_PROVIDER=$($Config.Primary)"
        "LLM_PROVIDER_FALLBACK=$($Config.Fallback)"
        "LLM_PROVIDER_VISION=$($Config.Vision)"
        "LLM_PROVIDER_VISION_FALLBACK=ollama-local"
    )

    # OpenRouter
    if ($Config.OpenRouterKey -or $Config.Primary -eq "openrouter" -or $Config.Fallback -eq "openrouter") {
        $orModel = if ($Config.Primary -eq "openrouter") { $Config.Model } else { "openai/gpt-5-nano" }
        $lines += @(
            ""
            "# --- OpenRouter Configuration ---"
            "OPENROUTER_API_KEY=$($Config.OpenRouterKey)"
            "OPENROUTER_SITE_URL=http://localhost:8000"
            "OPENROUTER_APP_NAME=AWP"
            "OPENROUTER_MODEL=$orModel"
            "OPENROUTER_MODEL_EXECUTOR=$orModel"
            "OPENROUTER_MODEL_VISION=nvidia/nemotron-nano-12b-v2-vl:free"
            "OPENROUTER_MODEL_MEMORY=$orModel"
        )
    }

    # Ollama
    if ($Config.Primary -eq "ollama" -or $Config.Fallback -eq "ollama" -or $Config.Vision -eq "ollama") {
        $lines += @(
            ""
            "# --- Ollama Configuration ---"
            "OLLAMA_BASE_URL=$($Config.OllamaBaseUrl)"
            "OLLAMA_MODEL=$($Config.OllamaModel)"
            "OLLAMA_MODEL_EXECUTOR=$($Config.OllamaModel)"
            "OLLAMA_MODEL_VISION=qwen3-vl:cloud"
        )
    }

    # OpenAI
    if ($Config.OpenAIKey) {
        $lines += @("", "# --- OpenAI Configuration ---", "OPENAI_API_KEY=$($Config.OpenAIKey)")
    }

    # Groq
    if ($Config.GroqKey) {
        $lines += @("", "# --- Groq Configuration ---", "GROQ_API_KEY=$($Config.GroqKey)")
    }

    # Together
    if ($Config.TogetherKey) {
        $lines += @("", "# --- Together Configuration ---", "TOGETHER_API_KEY=$($Config.TogetherKey)")
    }

    # Custom
    if ($Config.CustomUrl) {
        $lines += @(
            ""
            "# --- Custom Provider Configuration ---"
            "LLM_BASE_URL=$($Config.CustomUrl)"
            "LLM_API_KEY=$($Config.CustomKey)"
            "LLM_MODEL=$($Config.CustomModel)"
        )
    }

    # Active model
    switch ($Config.Primary) {
        "openrouter" {
            $lines += @("", "# --- Active Model (used by AWP runtime) ---", "LLM_MODEL=$($Config.Model)")
        }
        "ollama" {
            $lines += @(
                "", "# --- Active Model (used by AWP runtime) ---"
                "LLM_MODEL=$($Config.Model)"
                "LLM_BASE_URL=$($Config.OllamaBaseUrl)/v1"
            )
        }
        "openai" {
            $lines += @("", "# --- Active Model (used by AWP runtime) ---", "LLM_MODEL=$($Config.Model)")
        }
        "groq" {
            $lines += @(
                "", "# --- Active Model (used by AWP runtime) ---"
                "LLM_MODEL=$($Config.Model)"
                "LLM_BASE_URL=https://api.groq.com/openai/v1"
                "LLM_API_KEY=$($Config.GroqKey)"
            )
        }
        "together" {
            $lines += @(
                "", "# --- Active Model (used by AWP runtime) ---"
                "LLM_MODEL=$($Config.Model)"
                "LLM_BASE_URL=https://api.together.xyz/v1"
                "LLM_API_KEY=$($Config.TogetherKey)"
            )
        }
    }

    $lines | Set-Content -Path $AWP_ENV -Encoding UTF8
    Write-Success "Configuration saved to $AWP_ENV"
}

function Write-MinimalEnv {
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss") + " UTC"
    @(
        "# ============================================================================="
        "# AWP - Agent Workflow Protocol :: Global Configuration"
        "# Generated by install.ps1 on $timestamp"
        "# ============================================================================="
        ""
        "# --- LLM Provider Selection ---"
        "LLM_PROVIDER=openrouter"
        "LLM_PROVIDER_FALLBACK=ollama"
        ""
        "# --- OpenRouter (get free key at https://openrouter.ai/keys) ---"
        "OPENROUTER_API_KEY="
        "OPENROUTER_MODEL=openai/gpt-5-nano"
        ""
        "# --- Ollama (cloud models by default) ---"
        "OLLAMA_BASE_URL=https://ollama.com"
        "OLLAMA_MODEL=nemotron-3-super:cloud"
        ""
        "# --- Active Model ---"
        "LLM_MODEL=openai/gpt-5-nano"
    ) | Set-Content -Path $AWP_ENV -Encoding UTF8
    Write-Success "Minimal config written to $AWP_ENV -- edit to add your API keys"
}

# -- Step 8: Verify installation -----------------------------------------------

function Test-Installation {
    Write-Host ""
    Write-Host "=== Verifying Installation ===" -ForegroundColor Cyan
    Write-Host ""

    $awpExe = Join-Path $AWP_VENV "Scripts\awp.exe"
    if (Test-Path $awpExe) {
        Write-Success "awp CLI installed"
    } else {
        Write-Err "awp CLI not found"
    }

    if (Test-Path $AWP_ENV) {
        Write-Success "Global config exists at $AWP_ENV"
    }

    $pythonExe = Join-Path $AWP_VENV "Scripts\python.exe"
    if (Test-Path $pythonExe) {
        $pyVer = & $pythonExe --version 2>&1
        Write-Success "Python venv: $pyVer"
    }

    $pipExe = Join-Path $AWP_VENV "Scripts\pip.exe"
    try {
        $pkgInfo = & $pipExe show awp-protocol 2>$null | Select-String "^Version:"
        if ($pkgInfo) {
            Write-Success "awp-protocol: v$($pkgInfo -replace 'Version:\s*', '')"
        }
    } catch { }
}

# -- Step 9: Print summary -----------------------------------------------------

function Write-Summary {
    Write-Host ""
    Write-Host "=== Installation Complete ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "  AWP Home:     $AWP_HOME"
    Write-Host "  Config:       $AWP_ENV"
    Write-Host "  CLI:          $AWP_BIN\awp.cmd"
    Write-Host "  Python venv:  $AWP_VENV"
    Write-Host ""
    Write-Host "Quick start:" -ForegroundColor White
    Write-Host ""
    Write-Host "  # Open a new terminal, then:"
    Write-Host "  awp validate examples\01-hello-world"
    Write-Host "  awp run examples\01-hello-world --task `"Hello World`""
    Write-Host "  awp visualize examples\02-research-pipeline --format mermaid"
    Write-Host ""
    Write-Host "Configuration:" -ForegroundColor White
    Write-Host "  Edit $AWP_ENV to change LLM providers and API keys."
    Write-Host "  Per-workflow settings in secrets.yaml or .env override globals."
    Write-Host ""
}

# -- Main ----------------------------------------------------------------------

function Main {
    Write-Banner

    Write-Host "This wizard will install AWP and configure your LLM providers." -ForegroundColor White
    Write-Host ""
    $confirm = Read-Host "Continue with installation? [Y/n]"
    if ($confirm -eq "n") {
        Write-Host "Installation cancelled."
        exit 0
    }

    Write-Host ""
    Write-Host "=== Step 1: System Requirements ===" -ForegroundColor Cyan
    $pythonCmd = Test-PythonVersion
    Test-Git
    Test-Ollama

    Write-Host ""
    Write-Host "=== Step 2: AWP Setup ===" -ForegroundColor Cyan
    Initialize-AwpHome
    Initialize-Venv -PythonCmd $pythonCmd
    Install-Awp
    New-CliWrapper
    Add-ToPath

    Write-Host ""
    Write-Host "=== Step 3: LLM Configuration ===" -ForegroundColor Cyan
    Start-SetupWizard

    Test-Installation
    Write-Summary
}

Main
