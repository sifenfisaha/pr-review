#!/usr/bin/env bash
set -eu
git clone -q "$(dirname "$0")/files/shop.bundle" shop
git -C shop checkout -q feature/coupons
