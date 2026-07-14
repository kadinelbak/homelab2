#!/bin/bash
# set-ollama-model.sh
# Utility to change the default Ollama model

set -euo pipefail

# Default Ollama host
OLLAMA_HOST=${OLLAMA_HOST:-http://ollama:11434}

# Show usage
if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <model-name>"
  echo "Example: $0 llama3"
  echo "Example: $0 mistral"
  echo ""
  echo "To see available models: curl -s http://ollama:11434/api/tags"
  exit 1
fi

MODEL_NAME="$1"

echo "Setting default Ollama model to: $MODEL_NAME"

# Check if Ollama is accessible
if ! curl -s -o /dev/null -w "%{http_code}" "${OLLAMA_HOST}/api/tags"; then
  echo "Error: Cannot connect to Ollama at $OLLAMA_HOST"
  exit 1
fi

# Check if the model exists locally
if curl -s "${OLLAMA_HOST}/api/tags" | grep -q "\"name\": \"$MODEL_NAME\""; then
  echo "Model $MODEL_NAME is already available locally"
else
  echo "Pulling model $MODEL_NAME..."
  # Pull the model
  curl -s -X POST "${OLLAMA_HOST}/api/pull" -d "{\"name\": \"$MODEL_NAME\"}" > /dev/null
  echo "Model $MODEL_NAME pulled successfully"
fi

# Update the default model in .env if it exists
if [[ -f "../.env" ]]; then
  # Check if OLLAMA_MODEL already exists
  if grep -q "^OLLAMA_MODEL=" ../.env; then
    # Update existing value
    sed -i "s/^OLLAMA_MODEL=.*/OLLAMA_MODEL=$MODEL_NAME/" ../.env
    echo "Updated OLLAMA_MODEL in .env to $MODEL_NAME"
  else
    # Add new value
    echo "OLLAMA_MODEL=$MODEL_NAME" >> ../.env
    echo "Added OLLAMA_MODEL=$MODEL_NAME to .env"
  fi
else
  echo "Warning: .env file not found. Model setting not persisted."
fi

echo "Default Ollama model is now set to: $MODEL_NAME"
echo "You can test it with: ./scripts/ollama-query.sh \"Hello world\" $MODEL_NAME"