#!/bin/bash
set -e
rm -rf /data/safeline
mkdir -p /data/safeline
cd /data/safeline

# Download compose
curl -fsSLk https://waf-ce.chaitin.cn/release/latest/compose.yaml -o compose.yaml

# Pull all images
IMAGES="safeline-mgt:9.3.8 safeline-tengine:9.3.8 safeline-detector:9.3.8 safeline-luigi:9.3.8 safeline-fvm:9.3.8 safeline-chaos:9.3.8 safeline-postgres:15.2"

for img in $IMAGES; do
  echo "--- Pulling chaitin/$img ---"
  docker pull "chaitin/$img"
done

echo "=== ALL IMAGES PULLED ==="
