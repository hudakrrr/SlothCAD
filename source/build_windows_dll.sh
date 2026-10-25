#!/usr/bin/env bash
# Cross-compile the viewport DLL for 64-bit Windows from Linux (maintainers only).
# Needs clang and lld-link. The DLL uses no C runtime, so it needs no redistributables.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
digest=$(python3 -c 'import build_renderer as b;print(b.source_digest())')
mkdir -p .native
obj=$(mktemp --suffix=.obj)
clang --target=x86_64-pc-windows-msvc -O3 -std=c99 -DSLOTHCAD_FREESTANDING -ffreestanding \
      -fno-stack-protector -fno-builtin -c native_raster.c -o "$obj"
lld-link /dll /noentry /nodefaultlib /machine:x64 /out:".native/raster-x86_64-$digest.dll" "$obj"
rm -f "$obj" ".native/raster-x86_64-$digest.lib"
echo "Built .native/raster-x86_64-$digest.dll"
