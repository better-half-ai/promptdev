#!/usr/bin/env bash
set -euo pipefail

# Model selection (default: dolphin)
MODEL="${1:-dolphin}"

MODEL_DIR="models"

# Model configurations
declare -A MODEL_FILES=(
    [dolphin]="dolphin-2.2.1-mistral-7b.Q4_K_M.gguf"
    [venice]="venice-24b.Q4_K_M.gguf"
)

declare -A MODEL_URLS=(
    [dolphin]="https://huggingface.co/TheBloke/dolphin-2.2.1-mistral-7B-GGUF/resolve/main/dolphin-2.2.1-mistral-7b.Q4_K_M.gguf"
    [venice]="https://huggingface.co/mradermacher/Dolphin-Mistral-24B-Venice-Edition-GGUF/resolve/main/Dolphin-Mistral-24B-Venice-Edition.Q4_K_M.gguf"
)

declare -A MODEL_SIZES=(
    [dolphin]="4.4GB"
    [venice]="14GB"
)

declare -A MODEL_DESCRIPTIONS=(
    [dolphin]="Dolphin 7B - Very uncensored"
    [venice]="Venice 24B - Most uncensored"
)

# Validate model choice
if [[ ! -v MODEL_FILES[$MODEL] ]]; then
    echo "ERROR: Invalid model '$MODEL'"
    echo ""
    echo "Available models:"
    echo "  dolphin  - Dolphin 7B (4.4GB, very uncensored) [DEFAULT]"
    echo "  venice   - Venice 24B (14GB, most uncensored)"
    echo ""
    echo "Usage: $0 [dolphin|venice]"
    exit 1
fi

MODEL_FILE="${MODEL_FILES[$MODEL]}"
MODEL_PATH="${MODEL_DIR}/${MODEL_FILE}"
MODEL_URL="${MODEL_URLS[$MODEL]}"
MODEL_SIZE="${MODEL_SIZES[$MODEL]}"
MODEL_DESC="${MODEL_DESCRIPTIONS[$MODEL]}"

echo "==> Setting up ${MODEL_DESC} on Mac"
echo ""

# Check if llama.cpp is installed
if ! command -v llama-server &> /dev/null; then
    echo "==> Installing llama.cpp via Homebrew..."
    brew install llama.cpp
else
    echo "==> llama.cpp already installed ✓"
fi

# Create models directory
mkdir -p "${MODEL_DIR}"

# Download model if not exists
if [ ! -f "${MODEL_PATH}" ]; then
    echo "==> Downloading ${MODEL_DESC} (~${MODEL_SIZE})..."
    echo "    This may take 5-15 minutes depending on model"
    echo ""
    
    curl -L -C - --retry 10 --retry-delay 5 --retry-max-time 7200 \
        -o "${MODEL_PATH}" \
        "${MODEL_URL}"
    
    echo ""
    echo "==> Download complete ✓"
else
    echo "==> Model already exists at ${MODEL_PATH} ✓"
fi

# Run server
echo ""
echo "==> Starting ${MODEL_DESC} on http://127.0.0.1:8080"
echo "    Press Ctrl+C to stop"
echo ""

# Adjust settings based on model
if [ "$MODEL" = "venice" ]; then
    THREADS=8
    CTX_SIZE=8192
else
    THREADS=6
    CTX_SIZE=4096
fi

exec llama-server \
    --model "${MODEL_PATH}" \
    --host 127.0.0.1 \
    --port 8080 \
    --threads ${THREADS} \
    --ctx-size ${CTX_SIZE} \
    --n-gpu-layers 999
