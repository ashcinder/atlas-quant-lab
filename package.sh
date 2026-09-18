#!/bin/bash
set -e
cd "$(dirname "$0")"

IMAGE_NAME="atlas-quant"
IMAGE_TAG="${1:-latest}"

echo "Building image..."
docker build -t "$IMAGE_NAME:$IMAGE_TAG" .

echo ""
echo "Tagging for push..."
docker tag "$IMAGE_NAME:$IMAGE_TAG" "your-dockerhub-username/$IMAGE_NAME:$IMAGE_TAG"
docker tag "$IMAGE_NAME:$IMAGE_TAG" "your-dockerhub-username/$IMAGE_NAME:latest"

echo ""
echo "Push to Docker Hub:"
echo "  docker push your-dockerhub-username/$IMAGE_NAME:$IMAGE_TAG"
echo "  docker push your-dockerhub-username/$IMAGE_NAME:latest"
