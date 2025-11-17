#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="models"
MODEL_FILE="mistral-7b-instruct-v0.2.Q4_K_M.gguf"
MODEL_PATH="${MODEL_DIR}/${MODEL_FILE}"
MODEL_URL="https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/${MODEL_FILE}"

echo "==> Setting up Mistral locally on Mac"

# Check if llama.cpp is installed
if ! command -v llama-server &> /dev/null; then
    echo "==> Installing llama.cpp via Homebrew..."
    brew install llama.cpp
else
    echo "==> llama.cpp already installed"
fi

# Create models directory
mkdir -p "${MODEL_DIR}"

# Download model if not exists
if [ ! -f "${MODEL_PATH}" ]; then
    echo "==> Downloading Mistral model (~4GB)..."
    wget -O "${MODEL_PATH}" "${MODEL_URL}"
    echo "==> Download complete"
else
    echo "==> Model already exists at ${MODEL_PATH}"
fi

# Run server
echo "==> Starting Mistral server on http://127.0.0.1:8080"
echo "    Press Ctrl+C to stop"
echo ""

llama-server \
    --model "${MODEL_PATH}" \
    --host 127.0.0.1 \
    --port 8080 \
    --threads 6 \
    --ctx-size 4096