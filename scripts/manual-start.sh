#!/bin/sh
set -eu

cd /app
./migrate
exec ./server
