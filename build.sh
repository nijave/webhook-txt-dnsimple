#!/bin/sh

set -eu

TODAY=$(date +%Y%m%d)

REGISTRY=ghcr.io
IMAGE_BASE=nijave/webhook-dyn-dnsimple

docker build \
	-t $REGISTRY/$IMAGE_BASE \
	-t $REGISTRY/$IMAGE_BASE:$TODAY \
	.

docker push $REGISTRY/$IMAGE_BASE
docker push $REGISTRY/$IMAGE_BASE:$TODAY
