#!/usr/bin/env bash
# =============================================================================
# AWP - Agent Workflow Protocol :: Installation Script
# Supports: Linux, macOS
# Creates: ~/.awp/ with venv, global .env config, and 'awp' CLI on PATH
# =============================================================================

set -euo pipefail

# -- Colors & helpers ---------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }

banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    echo "    ___  _      ______"
    echo "   /   || | /| / / __ \\"
    echo "  / /| || |/ |/ / /_/ /"
    echo " / ___ ||__/|__/ ____/"
    echo "/_/  |_|       /_/"
    echo ""
    echo "  Agent Workflow Protocol"
    echo "  Installation Wizard"
    echo -e "${NC}"
}

AWP_HOME="$HOME/.awp"
AWP_VENV="$AWP_HOME/venv"
AWP_ENV="$AWP_HOME/.env"
AWP_BIN="$AWP_HOME/bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIN_PYTHON_VERSION="3.10"

# -- Step 1: System checks ----------------------------------------------------

check_python() {
    info "Checking Python version..."

    local python_cmd=""
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            local major minor
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                python_cmd="$cmd"
                success "Found $cmd ($ver)"
                break
            fi
        fi
    done

    if [ -z "$python_cmd" ]; then
        error "Python >= $MIN_PYTHON_VERSION is required but not found."
        echo ""
        echo "Install Python:"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "  brew install python@3.12"
        else
            echo "  sudo apt install python3.12 python3.12-venv  (Debian/Ubuntu)"
            echo "  sudo dnf install python3.12                  (Fedora)"
            echo "  sudo pacman -S python                        (Arch)"
        fi
        exit 1
    fi

    PYTHON_CMD="$python_cmd"
}

check_pip() {
    info "Checking pip..."
    if "$PYTHON_CMD" -m pip --version &>/dev/null; then
        success "pip available"
    else
        warn "pip not found, attempting to install..."
        "$PYTHON_CMD" -m ensurepip --upgrade 2>/dev/null || {
            error "Could not install pip. Please install it manually."
            exit 1
        }
        success "pip installed"
    fi
}

check_git() {
    info "Checking git..."
    if command -v git &>/dev/null; then
        success "git available ($(git --version | cut -d' ' -f3))"
    else
        warn "git not found. Installing..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            xcode-select --install 2>/dev/null || true
        elif command -v apt &>/dev/null; then
            sudo apt install -y git
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y git
        elif command -v pacman &>/dev/null; then
            sudo pacman -S --noconfirm git
        else
            error "Please install git manually."
            exit 1
        fi
        success "git installed"
    fi
}

check_ollama() {
    info "Checking Ollama..."
    if command -v ollama &>/dev/null; then
        success "Ollama available"
        OLLAMA_INSTALLED=true
    else
        OLLAMA_INSTALLED=false
        echo ""
        echo -e "${YELLOW}Ollama is not installed.${NC}"
        echo "Ollama provides cloud and local LLM inference."
        echo ""
        read -rp "Install Ollama now? [Y/n]: " install_ollama
        install_ollama="${install_ollama:-Y}"
        if [[ "$install_ollama" =~ ^[Yy]$ ]]; then
            info "Installing Ollama..."
            curl -fsSL https://ollama.com/install.sh | sh
            if command -v ollama &>/dev/null; then
                success "Ollama installed"
                OLLAMA_INSTALLED=true
            else
                warn "Ollama installation may require a restart. Continuing..."
            fi
        else
            info "Skipping Ollama installation"
        fi
    fi
}

check_existing_awp() {
    # Detect conflicting awp installations (e.g., in conda/pip global)
    local existing
    existing=$(command -v awp 2>/dev/null || true)
    if [ -n "$existing" ] && [ "$existing" != "$AWP_BIN/awp" ]; then
        warn "Found existing 'awp' at: $existing"
        echo "  This may conflict with the new installation at $AWP_BIN/awp."

        # Check if it's in a conda/pip environment
        if echo "$existing" | grep -q "anaconda\|miniconda\|conda"; then
            echo ""
            echo -e "${YELLOW}  A conda-installed awp was detected.${NC}"
            read -rp "  Remove awp-protocol from conda to avoid conflicts? [Y/n]: " remove_conda
            remove_conda="${remove_conda:-Y}"
            if [[ "$remove_conda" =~ ^[Yy]$ ]]; then
                local conda_pip
                conda_pip="$(dirname "$existing")/pip"
                if [ -x "$conda_pip" ]; then
                    "$conda_pip" uninstall awp-protocol -y 2>/dev/null || true
                    success "Removed awp-protocol from conda"
                fi
            fi
        else
            echo -e "  ${YELLOW}Ensure $AWP_BIN is before $(dirname "$existing") in your PATH.${NC}"
        fi
    fi
}

# -- Step 2: Create AWP home --------------------------------------------------

setup_awp_home() {
    info "Setting up AWP home directory at $AWP_HOME..."
    mkdir -p "$AWP_HOME"
    mkdir -p "$AWP_BIN"
    success "AWP home ready: $AWP_HOME"
}

# -- Step 3: Virtual environment -----------------------------------------------

setup_venv() {
    if [ -d "$AWP_VENV" ]; then
        info "Existing venv found at $AWP_VENV"
        read -rp "Recreate virtual environment? [y/N]: " recreate
        if [[ "$recreate" =~ ^[Yy]$ ]]; then
            rm -rf "$AWP_VENV"
        else
            info "Reusing existing venv"
            return
        fi
    fi

    info "Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$AWP_VENV"
    success "Virtual environment created"
}

# -- Step 4: Install AWP package -----------------------------------------------

install_awp() {
    info "Installing AWP Protocol..."
    local pip="$AWP_VENV/bin/pip"

    # Upgrade pip first
    "$pip" install --upgrade pip setuptools wheel -q

    # Try PyPI first, then local
    if "$pip" install awp-protocol -q 2>/dev/null; then
        success "Installed awp-protocol from PyPI"
    elif [ -f "$SCRIPT_DIR/reference/python/pyproject.toml" ]; then
        info "PyPI package not found. Installing from local source..."
        "$pip" install -e "$SCRIPT_DIR/reference/python" -q
        success "Installed awp-protocol from local source"
    else
        info "Installing from GitHub..."
        "$pip" install "git+https://github.com/veegee82/agent-workflow-protocol.git#subdirectory=reference/python" -q
        success "Installed awp-protocol from GitHub"
    fi

    # Install common workflow dependencies
    info "Installing common workflow dependencies..."
    "$pip" install ddgs httpx -q 2>/dev/null || true

    # Verify installation
    if "$AWP_VENV/bin/awp" --help &>/dev/null; then
        success "AWP CLI verified"
    else
        error "AWP CLI installation failed"
        exit 1
    fi
}

# -- Step 5: Create CLI wrapper ------------------------------------------------

create_cli_wrapper() {
    info "Creating AWP CLI wrapper..."

    cat > "$AWP_BIN/awp" << 'WRAPPER'
#!/usr/bin/env bash
# AWP CLI wrapper -- activates venv and runs awp
AWP_HOME="$HOME/.awp"
AWP_VENV="$AWP_HOME/venv"
AWP_ENV="$AWP_HOME/.env"

# Load global .env if it exists
if [ -f "$AWP_ENV" ]; then
    set -a
    source "$AWP_ENV"
    set +a
fi

# Run awp from venv
exec "$AWP_VENV/bin/awp" "$@"
WRAPPER

    chmod +x "$AWP_BIN/awp"
    success "CLI wrapper created at $AWP_BIN/awp"
}

# -- Step 6: Add to PATH ------------------------------------------------------

add_to_path() {
    local shell_rc=""
    local current_shell
    current_shell="$(basename "$SHELL")"

    case "$current_shell" in
        zsh)  shell_rc="$HOME/.zshrc" ;;
        bash)
            if [ -f "$HOME/.bash_profile" ]; then
                shell_rc="$HOME/.bash_profile"
            else
                shell_rc="$HOME/.bashrc"
            fi
            ;;
        fish) shell_rc="$HOME/.config/fish/config.fish" ;;
        *)    shell_rc="$HOME/.profile" ;;
    esac

    local path_line='export PATH="$HOME/.awp/bin:$PATH"'
    if [ "$current_shell" = "fish" ]; then
        path_line='set -gx PATH $HOME/.awp/bin $PATH'
    fi

    if [ -f "$shell_rc" ] && grep -q '.awp/bin' "$shell_rc" 2>/dev/null; then
        info "PATH already configured in $shell_rc"
    else
        echo "" >> "$shell_rc"
        echo "# AWP - Agent Workflow Protocol" >> "$shell_rc"
        echo "$path_line" >> "$shell_rc"
        success "Added to PATH in $shell_rc"
    fi

    # Also export for current session
    export PATH="$AWP_BIN:$PATH"
}

# -- Step 7: Setup Wizard (LLM Configuration) ---------------------------------

setup_wizard() {
    echo ""
    echo -e "${CYAN}${BOLD}=== LLM Provider Configuration ===${NC}"
    echo ""
    echo "AWP needs an LLM provider to run agent workflows."
    echo "You can change these settings later by editing: $AWP_ENV"
    echo ""
    echo "Available providers:"
    echo "  1) OpenRouter  (cloud, free tier available, recommended)"
    echo "  2) Ollama      (cloud & local, uses cloud models by default)"
    echo "  3) OpenAI      (cloud, requires paid API key)"
    echo "  4) Groq        (cloud, free tier available)"
    echo "  5) Together    (cloud, free tier available)"
    echo "  6) Custom      (any OpenAI-compatible endpoint)"
    echo "  7) Skip        (configure later)"
    echo ""

    local primary_provider=""
    local fallback_provider=""
    local vision_provider=""

    # -- Primary Provider --
    read -rp "Select PRIMARY LLM provider [1]: " provider_choice
    provider_choice="${provider_choice:-1}"

    case "$provider_choice" in
        1) primary_provider="openrouter" ;;
        2) primary_provider="ollama" ;;
        3) primary_provider="openai" ;;
        4) primary_provider="groq" ;;
        5) primary_provider="together" ;;
        6) primary_provider="custom" ;;
        7)
            warn "Skipping LLM configuration. Edit $AWP_ENV later."
            write_minimal_env
            return
            ;;
        *) primary_provider="openrouter" ;;
    esac

    # -- Collect API keys & settings based on provider --
    local openrouter_key=""
    local ollama_base_url="https://ollama.com"
    local ollama_model="nemotron-3-super:cloud"
    local openai_key=""
    local groq_key=""
    local together_key=""
    local custom_url=""
    local custom_key=""
    local custom_model=""

    local primary_model=""

    collect_provider_config "$primary_provider"

    # -- Fallback Provider --
    echo ""
    echo -e "${CYAN}Fallback provider (used when primary is unavailable):${NC}"
    if [ "$primary_provider" = "openrouter" ]; then
        echo "  Default: ollama (local fallback)"
        read -rp "Use Ollama as fallback? [Y/n]: " use_ollama_fallback
        use_ollama_fallback="${use_ollama_fallback:-Y}"
        if [[ "$use_ollama_fallback" =~ ^[Yy]$ ]]; then
            fallback_provider="ollama"
            if [ -z "$ollama_model" ] || [ "$ollama_model" = "nemotron-3-super:cloud" ]; then
                read -rp "Ollama fallback model [nemotron-3-super:cloud]: " ollama_model
                ollama_model="${ollama_model:-nemotron-3-super:cloud}"
            fi
        else
            fallback_provider="none"
        fi
    elif [ "$primary_provider" = "ollama" ]; then
        echo "  Default: openrouter (cloud fallback)"
        read -rp "Use OpenRouter as fallback? [Y/n]: " use_or_fallback
        use_or_fallback="${use_or_fallback:-Y}"
        if [[ "$use_or_fallback" =~ ^[Yy]$ ]]; then
            fallback_provider="openrouter"
            if [ -z "$openrouter_key" ]; then
                read -rp "OpenRouter API key (get free at openrouter.ai): " openrouter_key
            fi
        else
            fallback_provider="none"
        fi
    else
        fallback_provider="ollama"
    fi

    # -- Vision Provider --
    echo ""
    echo -e "${CYAN}Vision provider (for image processing tasks):${NC}"
    echo "  Cloud-first: uses cloud vision models by default."
    echo "  Options: ollama (cloud), openrouter, openai"
    read -rp "Vision provider [ollama]: " vision_choice
    vision_choice="${vision_choice:-ollama}"
    case "$vision_choice" in
        openrouter) vision_provider="openrouter" ;;
        openai)     vision_provider="openai" ;;
        *)          vision_provider="ollama" ;;
    esac

    # -- Write .env --
    write_env_file "$primary_provider" "$fallback_provider" "$vision_provider" \
        "$openrouter_key" "$ollama_base_url" "$ollama_model" \
        "$openai_key" "$groq_key" "$together_key" \
        "$custom_url" "$custom_key" "$custom_model" \
        "$primary_model"

    # -- Pull Ollama models if needed --
    if [ "$OLLAMA_INSTALLED" = true ]; then
        if [ "$primary_provider" = "ollama" ] || [ "$fallback_provider" = "ollama" ] || [ "$vision_provider" = "ollama" ]; then
            echo ""
            read -rp "Pull Ollama models now? (requires Ollama running) [Y/n]: " pull_models
            pull_models="${pull_models:-Y}"
            if [[ "$pull_models" =~ ^[Yy]$ ]]; then
                pull_ollama_models "$primary_provider" "$ollama_model" "$vision_provider"
            fi
        fi
    fi
}

collect_provider_config() {
    local provider="$1"

    case "$provider" in
        openrouter)
            echo ""
            echo -e "${CYAN}OpenRouter Configuration:${NC}"
            echo "  Get a free API key at: https://openrouter.ai/keys"
            echo ""
            read -rp "OpenRouter API key: " openrouter_key
            read -rp "Model [openai/gpt-5-mini]: " primary_model
            primary_model="${primary_model:-openai/gpt-5-mini}"
            ;;
        ollama)
            echo ""
            echo -e "${CYAN}Ollama Configuration:${NC}"
            echo "  Ollama uses cloud models by default for best performance."
            echo "  Use ':cloud' suffix for cloud inference, or plain name for local."
            echo ""
            read -rp "Ollama base URL [https://ollama.com]: " ollama_base_url
            ollama_base_url="${ollama_base_url:-https://ollama.com}"
            read -rp "Model [nemotron-3-super:cloud]: " primary_model
            primary_model="${primary_model:-nemotron-3-super:cloud}"
            ollama_model="$primary_model"
            ;;
        openai)
            echo ""
            echo -e "${CYAN}OpenAI Configuration:${NC}"
            read -rp "OpenAI API key: " openai_key
            read -rp "Model [gpt-4o]: " primary_model
            primary_model="${primary_model:-gpt-4o}"
            ;;
        groq)
            echo ""
            echo -e "${CYAN}Groq Configuration:${NC}"
            echo "  Get a free API key at: https://console.groq.com/keys"
            read -rp "Groq API key: " groq_key
            read -rp "Model [llama-3.3-70b-versatile]: " primary_model
            primary_model="${primary_model:-llama-3.3-70b-versatile}"
            ;;
        together)
            echo ""
            echo -e "${CYAN}Together Configuration:${NC}"
            read -rp "Together API key: " together_key
            read -rp "Model [meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo]: " primary_model
            primary_model="${primary_model:-meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo}"
            ;;
        custom)
            echo ""
            echo -e "${CYAN}Custom Provider Configuration:${NC}"
            read -rp "Base URL (OpenAI-compatible): " custom_url
            read -rp "API key (leave empty if none): " custom_key
            read -rp "Model name: " custom_model
            primary_model="$custom_model"
            ;;
    esac
}

write_env_file() {
    local primary="$1"
    local fallback="$2"
    local vision="$3"
    local or_key="$4"
    local ol_url="$5"
    local ol_model="$6"
    local oai_key="$7"
    local groq_key="$8"
    local tog_key="$9"
    local cust_url="${10}"
    local cust_key="${11}"
    local cust_model="${12}"
    local model="${13}"

    info "Writing global configuration to $AWP_ENV..."

    cat > "$AWP_ENV" << EOF
# =============================================================================
# AWP - Agent Workflow Protocol :: Global Configuration
# Generated by install.sh on $(date -u +"%Y-%m-%d %H:%M:%S UTC")
#
# This file provides FALLBACK values for LLM configuration.
# Workflow-level secrets.yaml and .env files take precedence.
#
# Edit this file to change your default LLM provider settings.
# =============================================================================

# --- LLM Provider Selection ---
LLM_PROVIDER=${primary}
LLM_PROVIDER_FALLBACK=${fallback}
LLM_PROVIDER_VISION=${vision}
LLM_PROVIDER_VISION_FALLBACK=ollama-local
EOF

    # OpenRouter config
    if [ -n "$or_key" ] || [ "$primary" = "openrouter" ] || [ "$fallback" = "openrouter" ]; then
        cat >> "$AWP_ENV" << EOF

# --- OpenRouter Configuration ---
OPENROUTER_API_KEY=${or_key}
OPENROUTER_SITE_URL=http://localhost:8000
OPENROUTER_APP_NAME=AWP
OPENROUTER_MODEL=${model:-openai/gpt-5-mini}
OPENROUTER_MODEL_EXECUTOR=${model:-openai/gpt-5-mini}
OPENROUTER_MODEL_VISION=nvidia/nemotron-nano-12b-v2-vl:free
OPENROUTER_MODEL_MEMORY=${model:-openai/gpt-5-mini}
EOF
    fi

    # Ollama config
    if [ "$primary" = "ollama" ] || [ "$fallback" = "ollama" ] || [ "$vision" = "ollama" ]; then
        cat >> "$AWP_ENV" << EOF

# --- Ollama Configuration ---
OLLAMA_BASE_URL=${ol_url:-https://ollama.com}
OLLAMA_MODEL=${ol_model:-nemotron-3-super:cloud}
OLLAMA_MODEL_EXECUTOR=${ol_model:-nemotron-3-super:cloud}
OLLAMA_MODEL_VISION=qwen3-vl:cloud
EOF
    fi

    # OpenAI config
    if [ -n "$oai_key" ]; then
        cat >> "$AWP_ENV" << EOF

# --- OpenAI Configuration ---
OPENAI_API_KEY=${oai_key}
EOF
    fi

    # Groq config
    if [ -n "$groq_key" ]; then
        cat >> "$AWP_ENV" << EOF

# --- Groq Configuration ---
GROQ_API_KEY=${groq_key}
EOF
    fi

    # Together config
    if [ -n "$tog_key" ]; then
        cat >> "$AWP_ENV" << EOF

# --- Together Configuration ---
TOGETHER_API_KEY=${tog_key}
EOF
    fi

    # Custom config
    if [ -n "$cust_url" ]; then
        cat >> "$AWP_ENV" << EOF

# --- Custom Provider Configuration ---
LLM_BASE_URL=${cust_url}
LLM_API_KEY=${cust_key}
LLM_MODEL=${cust_model}
EOF
    fi

    # Set default LLM_MODEL based on primary provider
    case "$primary" in
        openrouter)
            echo "" >> "$AWP_ENV"
            echo "# --- Active Model (used by AWP runtime) ---" >> "$AWP_ENV"
            echo "LLM_MODEL=${model:-openai/gpt-5-mini}" >> "$AWP_ENV"
            ;;
        ollama)
            echo "" >> "$AWP_ENV"
            echo "# --- Active Model (used by AWP runtime) ---" >> "$AWP_ENV"
            echo "LLM_MODEL=${model:-nemotron-3-super:cloud}" >> "$AWP_ENV"
            echo "LLM_BASE_URL=${ol_url:-https://ollama.com}/v1" >> "$AWP_ENV"
            ;;
        openai)
            echo "" >> "$AWP_ENV"
            echo "# --- Active Model (used by AWP runtime) ---" >> "$AWP_ENV"
            echo "LLM_MODEL=${model:-gpt-4o}" >> "$AWP_ENV"
            ;;
        groq)
            echo "" >> "$AWP_ENV"
            echo "# --- Active Model (used by AWP runtime) ---" >> "$AWP_ENV"
            echo "LLM_MODEL=${model:-llama-3.3-70b-versatile}" >> "$AWP_ENV"
            echo "LLM_BASE_URL=https://api.groq.com/openai/v1" >> "$AWP_ENV"
            echo "LLM_API_KEY=${groq_key}" >> "$AWP_ENV"
            ;;
        together)
            echo "" >> "$AWP_ENV"
            echo "# --- Active Model (used by AWP runtime) ---" >> "$AWP_ENV"
            echo "LLM_MODEL=${model}" >> "$AWP_ENV"
            echo "LLM_BASE_URL=https://api.together.xyz/v1" >> "$AWP_ENV"
            echo "LLM_API_KEY=${tog_key}" >> "$AWP_ENV"
            ;;
        custom)
            # Already handled above
            ;;
    esac

    chmod 600 "$AWP_ENV"
    success "Configuration saved to $AWP_ENV (permissions: 600)"
}

write_minimal_env() {
    cat > "$AWP_ENV" << EOF
# =============================================================================
# AWP - Agent Workflow Protocol :: Global Configuration
# Generated by install.sh on $(date -u +"%Y-%m-%d %H:%M:%S UTC")
#
# Configure your LLM provider below.
# Docs: https://github.com/veegee82/agent-workflow-protocol
# =============================================================================

# --- LLM Provider Selection ---
LLM_PROVIDER=openrouter
LLM_PROVIDER_FALLBACK=ollama

# --- OpenRouter (get free key at https://openrouter.ai/keys) ---
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-5-mini

# --- Ollama (cloud models by default) ---
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_MODEL=nemotron-3-super:cloud

# --- Active Model ---
LLM_MODEL=openai/gpt-5-mini
EOF

    chmod 600 "$AWP_ENV"
    success "Minimal config written to $AWP_ENV -- edit to add your API keys"
}

pull_ollama_models() {
    local primary="$1"
    local model="$2"
    local vision="$3"

    # Start ollama if not running
    if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
        info "Starting Ollama service..."
        ollama serve &>/dev/null &
        sleep 2
    fi

    if [ "$primary" = "ollama" ] && [ -n "$model" ]; then
        info "Pulling model: $model (this may take a while)..."
        ollama pull "$model" || warn "Could not pull $model -- pull it later with: ollama pull $model"
    fi

    if [ "$vision" = "ollama" ]; then
        info "Pulling vision model: qwen3-vl:cloud..."
        ollama pull "qwen3-vl:cloud" 2>/dev/null || warn "Could not pull vision model -- pull it later"
    fi
}

# -- Step 8: Verify installation -----------------------------------------------

verify_installation() {
    echo ""
    echo -e "${CYAN}${BOLD}=== Verifying Installation ===${NC}"
    echo ""

    # Check awp command
    if "$AWP_BIN/awp" --help &>/dev/null; then
        success "awp CLI works"
    else
        error "awp CLI not working"
        return 1
    fi

    # Check .env exists
    if [ -f "$AWP_ENV" ]; then
        success "Global config exists at $AWP_ENV"
    else
        warn "Global config not found"
    fi

    # Check venv
    if [ -f "$AWP_VENV/bin/python" ]; then
        local py_ver
        py_ver=$("$AWP_VENV/bin/python" --version 2>&1)
        success "Python venv: $py_ver"
    fi

    # Check awp-protocol package
    if "$AWP_VENV/bin/pip" show awp-protocol &>/dev/null; then
        local pkg_ver
        pkg_ver=$("$AWP_VENV/bin/pip" show awp-protocol 2>/dev/null | grep "^Version:" | cut -d' ' -f2)
        success "awp-protocol: v${pkg_ver}"
    fi

    return 0
}

# -- Step 9: Print summary -----------------------------------------------------

print_summary() {
    echo ""
    echo -e "${GREEN}${BOLD}=== Installation Complete ===${NC}"
    echo ""
    echo "  AWP Home:     $AWP_HOME"
    echo "  Config:       $AWP_ENV"
    echo "  CLI:          $AWP_BIN/awp"
    echo "  Python venv:  $AWP_VENV"
    echo ""
    echo -e "${BOLD}Quick start:${NC}"
    echo ""
    echo "  # Reload your shell (or open a new terminal)"
    echo "  source ~/.bashrc  # or ~/.zshrc"
    echo ""
    echo "  # Validate a workflow"
    echo "  awp validate examples/01-hello-world"
    echo ""
    echo "  # Run a workflow"
    echo "  awp run examples/01-hello-world --task \"Hello World\""
    echo ""
    echo "  # Visualize a workflow"
    echo "  awp visualize examples/02-research-pipeline --format mermaid"
    echo ""
    echo -e "${BOLD}Configuration:${NC}"
    echo "  Edit $AWP_ENV to change LLM providers and API keys."
    echo "  Per-workflow settings in secrets.yaml or .env override globals."
    echo ""
}

# -- Main ----------------------------------------------------------------------

main() {
    banner

    echo -e "${BOLD}This wizard will install AWP and configure your LLM providers.${NC}"
    echo ""
    read -rp "Continue with installation? [Y/n]: " confirm
    confirm="${confirm:-Y}"
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi

    echo ""
    echo -e "${CYAN}${BOLD}=== Step 1: System Requirements ===${NC}"
    check_python
    check_pip
    check_git
    check_existing_awp
    check_ollama

    echo ""
    echo -e "${CYAN}${BOLD}=== Step 2: AWP Setup ===${NC}"
    setup_awp_home
    setup_venv
    install_awp
    create_cli_wrapper
    add_to_path

    echo ""
    echo -e "${CYAN}${BOLD}=== Step 3: LLM Configuration ===${NC}"
    setup_wizard

    verify_installation
    print_summary
}

main "$@"
