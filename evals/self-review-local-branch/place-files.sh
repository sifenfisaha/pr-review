#!/usr/bin/env bash
set -eu
git clone -q "$(dirname "$0")/files/directory.bundle" directory
git -C directory checkout -q feature/pagination
