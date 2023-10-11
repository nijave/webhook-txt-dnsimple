#!/bin/sh

gunicorn -w 1 --preload -b :8080 app:app
