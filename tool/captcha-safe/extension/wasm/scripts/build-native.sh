#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CC_BIN="${CC:-clang}"
BUILD_DIR="${CAPTCHA_SOLVER_NATIVE_BUILD_DIR:-/private/tmp/captcha-safe-wasm-native}"
OUTPUT="${BUILD_DIR}/native_test"
SANITIZER="${CAPTCHA_SOLVER_SANITIZER:-undefined}"

if ! command -v "${CC_BIN}" >/dev/null 2>&1; then
  echo "native solver build rejected: C compiler '${CC_BIN}' is unavailable" >&2
  exit 69
fi

mkdir -p "${BUILD_DIR}"

flags=(
  -std=c11
  -O2
  -g
  -Wall
  -Wextra
  -Werror
  -Wconversion
  -Wshadow
  -Wstrict-prototypes
  -pedantic
  -fno-omit-frame-pointer
  -I"${ROOT}/include"
)

case "${SANITIZER}" in
  none)
    ;;
  undefined)
    flags+=(-fsanitize=undefined)
    ;;
  address)
    flags+=(-fsanitize=address,undefined)
    ;;
  *)
    echo "native solver build rejected: unsupported sanitizer '${SANITIZER}'" >&2
    exit 64
    ;;
esac

"${CC_BIN}" "${flags[@]}" \
  "${ROOT}/src/captcha_solver.c" \
  "${ROOT}/tests/native_test.c" \
  -o "${OUTPUT}"

if [[ "${SANITIZER}" == "address" ]]; then
  ASAN_OPTIONS="${ASAN_OPTIONS:-detect_leaks=0:halt_on_error=1}" \
    UBSAN_OPTIONS="${UBSAN_OPTIONS:-halt_on_error=1}" \
    "${OUTPUT}"
else
  UBSAN_OPTIONS="${UBSAN_OPTIONS:-halt_on_error=1}" "${OUTPUT}"
fi

echo "native solver fixture: ${OUTPUT}"
