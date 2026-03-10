#!/bin/bash
# Run the TTV-Scribe pipeline

set -e

cd "$(dirname "$0")/.."

# Create audio output directory if it doesn't exist
mkdir -p "$AUDIO_OUTPUT_DIR"

# Run the pipeline
python -m src.pipeline