#!/usr/bin/env bash
set -e

# Builds the Lambda Layer zip containing the Python dependencies
# (requests, psycopg2-binary, boto3, etc.) needed by script.py.

LAYER_DIR="lambda_layer"
PACKAGE_DIR="$LAYER_DIR/python"
ZIP_PATH="$LAYER_DIR/layer.zip"

echo "Cleaning up previous build..."
rm -rf "$LAYER_DIR"
mkdir -p "$PACKAGE_DIR"

echo "Installing dependencies into $PACKAGE_DIR..."
pip install -r requirements.txt -t "$PACKAGE_DIR"

echo "Zipping layer..."
cd "$LAYER_DIR"
zip -r layer.zip python > /dev/null
cd ..

echo "Layer built at $ZIP_PATH"