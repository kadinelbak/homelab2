#!/bin/bash
# ollama-query.sh
# Simple CLI tool to query the shared Ollama instance

set -euo pipefail

# Default Ollama host - can be overridden by environment
OLLAMA_HOST=${OLLAMA_HOST:-http://ollama:11434}
MODEL=${OLLAMA_MODEL:-llama3}

# Show usage if no arguments
if [[ $# -eq 0 ]]; then
  echo "Usage: $0 \"prompt text\" [model]"
  echo "  prompt text: The text to send to the Llama model"
  echo "  model: Optional model name (defaults to $MODEL or OLLAMA_MODEL env var)"
  echo ""
  echo "Environment variables:"
  echo "  OLLAMA_HOST: Ollama API URL (default: $OLLAMA_HOST)"
  echo "  OLLAMA_MODEL: Default model to use (default: $MODEL)"
  echo ""
  echo "Example:"
  echo "  $0 \"Explain quantum computing in simple terms\""
  echo "  $0 \"Write a haiku about homelabs\" mistral"
  exit 1
fi

PROMPT="$1"
if [[ $# -ge 2 ]]; then
  MODEL="$2"
fi

# Query Ollama API
RESPONSE=$(curl -s -X POST "$OLLAMA_HOST/api/generate" \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"$MODEL\", \"prompt\": \"$PROMPT\", \"stream\": false}")

# Extract and print the response
echo "$RESPONSE" | jq -r '.response // .error // "Error: Unable to parse response"'