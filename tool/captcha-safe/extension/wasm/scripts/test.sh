#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="${CAPTCHA_SOLVER_TEST_ROOT:-/private/tmp/captcha-safe-wasm-tests}"
WASM_OUTPUT="${TEST_ROOT}/captcha_solver.$$.one.wasm"
WASM_OUTPUT_SECOND="${TEST_ROOT}/captcha_solver.$$.two.wasm"
WASM_METADATA="${WASM_OUTPUT}.build.json"
WASM_METADATA_SECOND="${WASM_OUTPUT_SECOND}.build.json"
PACKAGE_OUTPUT="${TEST_ROOT}/captcha_solver.$$.one.zip"
PACKAGE_OUTPUT_SECOND="${TEST_ROOT}/captcha_solver.$$.two.zip"
PYTHON_BIN="${PYTHON:-python3}"

CAPTCHA_SOLVER_NATIVE_BUILD_DIR="${TEST_ROOT}/native" \
  "${ROOT}/scripts/build-native.sh"

node --check "${ROOT}/tests/test_wasm.mjs"
node --check "${ROOT}/tests/test_loader.mjs"
node --check "${ROOT}/loader/captcha-solver-loader.mjs"
node --check "${ROOT}/tests/test_lock_verifier.mjs"
node --check "${ROOT}/scripts/verify-formal-lock.mjs"
"${PYTHON_BIN}" "${ROOT}/scripts/package-experimental.py" --help >/dev/null
node "${ROOT}/tests/test_lock_verifier.mjs"

set +e
node "${ROOT}/scripts/verify-formal-lock.mjs" >/dev/null 2>"${TEST_ROOT}/formal-lock.err"
formal_status=$?
set -e
if [[ ${formal_status} -ne 78 ]]; then
  echo "expected the PENDING formal lock to fail closed with status 78, got ${formal_status}" >&2
  exit 1
fi
echo "formal lock fail-closed test passed"

if [[ -e "${WASM_OUTPUT}" || -e "${WASM_METADATA}" || \
      -e "${WASM_OUTPUT_SECOND}" || -e "${WASM_METADATA_SECOND}" || \
      -e "${PACKAGE_OUTPUT}" || -e "${PACKAGE_OUTPUT_SECOND}" ]]; then
  echo "experimental WASM test rejected: the process-specific output path already exists" >&2
  exit 1
fi

set +e
CAPTCHA_SOLVER_ALLOW_PENDING_TOOLCHAIN=1 \
CAPTCHA_SOLVER_WASM_OUTPUT="${WASM_OUTPUT}" \
  "${ROOT}/scripts/build-wasm.sh"
wasm_status=$?
set -e

case ${wasm_status} in
  0)
    CAPTCHA_SOLVER_ALLOW_PENDING_TOOLCHAIN=1 \
    CAPTCHA_SOLVER_WASM_OUTPUT="${WASM_OUTPUT_SECOND}" \
      "${ROOT}/scripts/build-wasm.sh"
    if ! cmp -s "${WASM_OUTPUT}" "${WASM_OUTPUT_SECOND}"; then
      echo "experimental WASM builds are not byte-for-byte deterministic" >&2
      exit 1
    fi
    node "${ROOT}/tests/test_wasm.mjs" "${WASM_OUTPUT}"
    node "${ROOT}/tests/test_loader.mjs" \
      "${WASM_OUTPUT}" "${WASM_METADATA}" "${TEST_ROOT}/native/native_test"
    "${PYTHON_BIN}" "${ROOT}/scripts/package-experimental.py" build \
      --wasm "${WASM_OUTPUT}" \
      --metadata "${WASM_METADATA}" \
      --loader "${ROOT}/loader/captcha-solver-loader.mjs" \
      --output "${PACKAGE_OUTPUT}"
    "${PYTHON_BIN}" "${ROOT}/scripts/package-experimental.py" build \
      --wasm "${WASM_OUTPUT_SECOND}" \
      --metadata "${WASM_METADATA_SECOND}" \
      --loader "${ROOT}/loader/captcha-solver-loader.mjs" \
      --output "${PACKAGE_OUTPUT_SECOND}"
    if ! cmp -s "${PACKAGE_OUTPUT}" "${PACKAGE_OUTPUT_SECOND}"; then
      echo "experimental WASM packages are not byte-for-byte deterministic" >&2
      exit 1
    fi
    "${PYTHON_BIN}" "${ROOT}/scripts/package-experimental.py" verify \
      --package "${PACKAGE_OUTPUT}"
    wasm_summary="EXPERIMENTAL_WASM_EXECUTED_DETERMINISTIC"
    ;;
  69)
    if [[ -e "${WASM_OUTPUT}" || -e "${WASM_METADATA}" || \
          -e "${WASM_OUTPUT_SECOND}" || -e "${WASM_METADATA_SECOND}" || \
          -e "${PACKAGE_OUTPUT}" || -e "${PACKAGE_OUTPUT_SECOND}" ]]; then
      echo "experimental WASM build failed but left an output artifact" >&2
      exit 1
    fi
    wasm_summary="EXPERIMENTAL_NOT_EXECUTED"
    echo "${wasm_summary}: no wasm32 compiler is installed; no artifact was produced"
    ;;
  *)
    echo "unexpected WASM build status ${wasm_status}" >&2
    exit "${wasm_status}"
    ;;
esac

echo "native and lock-contract tests passed; ${wasm_summary}; formal readiness remains rejected"
