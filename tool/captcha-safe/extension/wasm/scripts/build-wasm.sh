#!/usr/bin/env bash
set -euo pipefail

export LC_ALL=C
export SOURCE_DATE_EPOCH=0
export TZ=UTC
export ZERO_AR_DATE=1
umask 022

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${CAPTCHA_SOLVER_BUILD_PROFILE:-minimal-dev}"
OUTPUT="${CAPTCHA_SOLVER_WASM_OUTPUT:-/private/tmp/captcha-safe-wasm-dev/captcha_solver.wasm}"
METADATA="${OUTPUT}.build.json"

if [[ "${PROFILE}" == "formal-opencv" ]]; then
  node "${ROOT}/scripts/verify-formal-lock.mjs"
  echo "formal WASM build rejected: the OpenCV/codec adapter is not implemented or verified" >&2
  exit 78
fi
if [[ "${PROFILE}" != "minimal-dev" ]]; then
  echo "WASM build rejected: unknown build profile '${PROFILE}'" >&2
  exit 64
fi
if [[ "${CAPTCHA_SOLVER_ALLOW_PENDING_TOOLCHAIN:-0}" != "1" ]]; then
  echo "WASM build rejected: toolchain-lock.json is PENDING" >&2
  echo "For a non-release experiment only, set CAPTCHA_SOLVER_ALLOW_PENDING_TOOLCHAIN=1." >&2
  exit 78
fi

mkdir -p "$(dirname -- "${OUTPUT}")"
TEMP_OUTPUT="${OUTPUT}.tmp.$$"
TEMP_METADATA="${METADATA}.tmp.$$"
trap 'rm -f -- "${TEMP_OUTPUT}" "${TEMP_METADATA}"' EXIT

exports=(
  solver_abi_version
  solver_config_size
  solver_result_size
  solver_target_rgb_capacity
  solver_background_rgb_capacity
  solver_target_rgb
  solver_background_rgb
  solver_config
  solver_result
  solver_reset
  solver_solve
)

compiler_kind=""
compiler_path=""
compiler_version=""
linker_path=""
linker_version=""
repro_command=""

candidate_clang="${WASM_CLANG:-clang}"
if command -v "${candidate_clang}" >/dev/null 2>&1 && \
   "${candidate_clang}" --print-targets 2>/dev/null | grep -Eq '(^|[[:space:]])wasm32([[:space:]]|$)'; then
  compiler_kind="llvm-wasm32"
  compiler_path="$(command -v "${candidate_clang}")"
  compiler_version="$("${candidate_clang}" --version | head -n 1)"
  candidate_lld="${WASM_LD:-}"
  if [[ -z "${candidate_lld}" && -x "$(dirname -- "${compiler_path}")/wasm-ld" ]]; then
    candidate_lld="$(dirname -- "${compiler_path}")/wasm-ld"
  fi
  if [[ -z "${candidate_lld}" ]]; then
    candidate_lld="$(command -v wasm-ld || true)"
  fi
  if [[ -z "${candidate_lld}" || ! -x "${candidate_lld}" ]]; then
    echo "WASM build rejected: clang has wasm32 but no executable wasm-ld was found" >&2
    echo "Set WASM_LD to the matching LLVM linker." >&2
    exit 69
  fi
  linker_path="$(CDPATH= cd -- "$(dirname -- "${candidate_lld}")" && pwd)/$(basename -- "${candidate_lld}")"
  linker_version="$("${linker_path}" --version | head -n 1)"
  compiler_major="$(printf '%s\n' "${compiler_version}" | sed -nE 's/.* version ([0-9]+).*/\1/p')"
  linker_major="$(printf '%s\n' "${linker_version}" | sed -nE 's/.*LLD ([0-9]+).*/\1/p')"
  if [[ -z "${compiler_major}" || -z "${linker_major}" || "${compiler_major}" != "${linker_major}" ]]; then
    echo "WASM build rejected: clang and wasm-ld major versions do not match" >&2
    exit 69
  fi
  link_exports=()
  for symbol in "${exports[@]}"; do
    link_exports+=("-Wl,--export=${symbol}")
  done
  "${candidate_clang}" \
    --target=wasm32-unknown-unknown \
    -std=c11 \
    -O3 \
    -nostdlib \
    -ffreestanding \
    -fno-builtin \
    -fvisibility=hidden \
    -ffile-prefix-map="${ROOT}=extension/wasm" \
    -fdebug-prefix-map="${ROOT}=extension/wasm" \
    -I"${ROOT}/include" \
    "${ROOT}/src/captcha_solver.c" \
    -fuse-ld="${linker_path}" \
    -Wl,--no-entry \
    -Wl,--export-memory \
    -Wl,--initial-memory=16777216 \
    -Wl,--max-memory=16777216 \
    -Wl,-z,stack-size=131072 \
    -Wl,--strip-all \
    -Wl,--fatal-warnings \
    "${link_exports[@]}" \
    -o "${TEMP_OUTPUT}"
  repro_command="CAPTCHA_SOLVER_ALLOW_PENDING_TOOLCHAIN=1 WASM_CLANG=${compiler_path} WASM_LD=${linker_path} ${ROOT}/scripts/build-wasm.sh"
elif command -v "${EMCC:-emcc}" >/dev/null 2>&1; then
  emcc_bin="${EMCC:-emcc}"
  compiler_kind="emscripten"
  compiler_path="$(command -v "${emcc_bin}")"
  compiler_version="$("${emcc_bin}" --version | head -n 1)"
  linker_path="EMCC_INTERNAL"
  linker_version="${compiler_version}"
  "${emcc_bin}" \
    -std=c11 \
    -O3 \
    -ffreestanding \
    -fno-builtin \
    -fvisibility=hidden \
    -ffile-prefix-map="${ROOT}=extension/wasm" \
    -fdebug-prefix-map="${ROOT}=extension/wasm" \
    -I"${ROOT}/include" \
    "${ROOT}/src/captcha_solver.c" \
    -Wl,--no-entry \
    -sSTANDALONE_WASM=1 \
    -sFILESYSTEM=0 \
    -sALLOW_MEMORY_GROWTH=0 \
    -sINITIAL_MEMORY=16777216 \
    -sMAXIMUM_MEMORY=16777216 \
    -sSTACK_SIZE=131072 \
    -sERROR_ON_UNDEFINED_SYMBOLS=1 \
    -sEXPORTED_FUNCTIONS='["_solver_abi_version","_solver_config_size","_solver_result_size","_solver_target_rgb_capacity","_solver_background_rgb_capacity","_solver_target_rgb","_solver_background_rgb","_solver_config","_solver_result","_solver_reset","_solver_solve"]' \
    -o "${TEMP_OUTPUT}"
  repro_command="CAPTCHA_SOLVER_ALLOW_PENDING_TOOLCHAIN=1 EMCC=${compiler_path} ${ROOT}/scripts/build-wasm.sh"
else
  echo "WASM build rejected: no clang with a wasm32 backend and no emcc were found" >&2
  echo "Apple Clang without a wasm32 target is intentionally not accepted." >&2
  exit 69
fi

if [[ ! -s "${TEMP_OUTPUT}" ]]; then
  echo "WASM build rejected: compiler produced no non-empty artifact" >&2
  exit 70
fi
chmod 0644 "${TEMP_OUTPUT}"

node - "${TEMP_METADATA}" "${TEMP_OUTPUT}" "${OUTPUT}" "${ROOT}/src/captcha_solver.c" \
  "${ROOT}/include/captcha_solver.h" "${compiler_kind}" "${compiler_path}" \
  "${compiler_version}" "${linker_path}" "${linker_version}" "${repro_command}" <<'NODE'
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";

const [metadataPath, artifactDigestPath, artifactPath, sourcePath, headerPath, compilerKind,
  compilerPath, compilerVersion, linkerPath, linkerVersion,
  reproducibleCommand] = process.argv.slice(2);
const digest = async (path) => createHash("sha256").update(await readFile(path)).digest("hex");
const metadata = {
  schemaVersion: 1,
  profile: "DEVELOPMENT_ONLY_MINIMAL_C11",
  solverReadiness: "PENDING",
  abiVersion: 1,
  algorithmId: "captcha-safe-canny-like-ncc-v1",
  artifact: artifactPath,
  artifactSha256: await digest(artifactDigestPath),
  sourceSha256: await digest(sourcePath),
  headerSha256: await digest(headerPath),
  compilerKind,
  compilerPath,
  compilerVersion,
  linkerPath,
  linkerVersion,
  fixedMemoryBytes: 16777216,
  sourceDateEpoch: 0,
  reproducibleCommand,
  containsOpenCv: false,
  containsImageCodecs: false,
  containsOnnx: false,
};
await writeFile(metadataPath, `${JSON.stringify(metadata, null, 2)}\n`, { flag: "w" });
NODE

chmod 0644 "${TEMP_METADATA}"
mv -f -- "${TEMP_OUTPUT}" "${OUTPUT}"
mv -f -- "${TEMP_METADATA}" "${METADATA}"
trap - EXIT

echo "development WASM artifact: ${OUTPUT}"
echo "development build metadata: ${METADATA}"
