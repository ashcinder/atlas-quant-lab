#!/bin/bash
set -e
cd "$(dirname "$0")/.."

IMAGE_NAME="atlas-quant"
IMAGE_TAG="${1:-latest}"

echo "Building Docker image: $IMAGE_NAME:$IMAGE_TAG"
docker build -t "$IMAGE_NAME:$IMAGE_TAG" .

echo ""
echo "Build complete!"
echo ""
echo "To run:"
echo "  docker run -d --name atlas-quant -p 8080:8080 $IMAGE_NAME:$IMAGE_TAG"
echo ""
echo "To run with custom settings:"
echo "  docker run -d --name atlas-quant \\"
echo "    -p 8080:8080 \\"
echo "    -e ATLAS_ALLOWED_ORIGINS=http://your-domain.com \\"
echo "    -e ATLAS_SESSION_SECRET=your-secret-key \\"
echo "    $IMAGE_NAME:$IMAGE_TAG"
