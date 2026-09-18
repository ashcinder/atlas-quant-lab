#!/bin/bash
set -e
cd "$(dirname "$0")/.."

IMAGE_NAME="atlas-quant"
IMAGE_TAG="latest"
CONTAINER_NAME="atlas-quant"

# Check if image exists
if ! docker image inspect "$IMAGE_NAME:$IMAGE_TAG" >/dev/null 2>&1; then
    echo "Image not found. Building..."
    ./deploy/build.sh "$IMAGE_TAG"
fi

# Stop and remove existing container if it exists
if [ "$(docker ps -a -q -f name="$CONTAINER_NAME")" ]; then
    echo "Removing existing container..."
    docker rm -f "$CONTAINER_NAME"
fi

# Run the container
echo "Starting Atlas Quant..."
docker run -d \
    --name "$CONTAINER_NAME" \
    -p 8080:8080 \
    --restart unless-stopped \
    "$IMAGE_NAME:$IMAGE_TAG"

echo ""
echo "Atlas Quant is starting..."
echo "Access the application at: http://localhost:8080"
echo ""
echo "To view logs:"
echo "  docker logs -f $CONTAINER_NAME"
echo ""
echo "To stop:"
echo "  docker stop $CONTAINER_NAME"
