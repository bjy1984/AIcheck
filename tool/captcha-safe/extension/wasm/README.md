# Auditable browser solver core

This directory contains a bounded C11 matching core and test fixtures for a
future browser extension worker. It is intentionally isolated from extension
UI, permissions, network capture, document binding, authorization, and drag
execution.

Current readiness is **PENDING**. Nothing here should enable an extension
action by itself. A MATCH from this core is only image-analysis evidence: it
can never authorize or enable a drag. Drag remains disabled unless an external,
independently verified extension readiness/authorization state permits it.

## What is implemented

- Fixed 16 MiB, non-growing-memory design with no heap allocation.
- Strict target/background dimensions, RGB capacities, and NCC work limits.
- RGB8 grayscale conversion.
- An explicitly named **Canny-like** Sobel/NMS/hysteresis edge detector.
- Binary normalized cross-correlation, deterministic row-major top-1, spatially
  distinct top-2, peak gap, and score-surface significance.
- Texture, adjacent-difference edge density, and local sharpness evidence.
- Versioned fixed-point ABI with MATCH, ABSTAIN, and controlled ERROR outcomes.
- Native C fixture plus a Node fixture that loads the real built WASM module.

See [ABI.md](ABI.md) for the byte-level contract.

## What is not implemented

- No PNG, JPEG, WebP, GIF, or other image decoder.
- No RGBA/alpha, ICC, EXIF, orientation, animation, or color-management logic.
- No OpenCV code or OpenCV.js artifact.
- No ONNX model or ONNX Runtime.
- No claim of ddddocr/OpenCV bit compatibility.
- No network fetch, DOM access, page-world JS, pointer event, or drag action.
- No formally reproducible release artifact while the lock is PENDING.

The checked-in Canny-like implementation is not OpenCV 5.0.0 parity and must
never be described as ddddocr-compatible. Its separate algorithm ID and PENDING
readiness are intentional.

Callers must supply tightly packed, canonical RGB8 pixels obtained through a
trusted path. Decoding in a page canvas can change color/alpha behavior and can
be blocked by cross-origin canvas tainting; it is not silently handled here.

## Run native tests

The default native build uses UBSan and writes only under `/private/tmp`:

```sh
extension/wasm/scripts/build-native.sh
```

Optional modes:

```sh
CAPTCHA_SOLVER_SANITIZER=none extension/wasm/scripts/build-native.sh
CAPTCHA_SOLVER_SANITIZER=address extension/wasm/scripts/build-native.sh
```

AddressSanitizer can be unusually slow with the deliberately large static WASM
buffers. UBSan is the default so routine tests remain fast.

## Build the minimal development WASM

The script accepts either:

- LLVM Clang with a real `wasm32` backend and its matching-major `wasm-ld`; or
- `emcc` producing standalone WASM.

Apple Clang without a wasm32 target is rejected. Because
`toolchain-lock.json` is PENDING, a development build requires an explicit
non-release acknowledgement:

```sh
CAPTCHA_SOLVER_ALLOW_PENDING_TOOLCHAIN=1 \
CAPTCHA_SOLVER_WASM_OUTPUT=/private/tmp/captcha-safe-wasm-dev/captcha_solver.wasm \
extension/wasm/scripts/build-wasm.sh
```

To choose a compiler explicitly:

```sh
CAPTCHA_SOLVER_ALLOW_PENDING_TOOLCHAIN=1 \
WASM_CLANG=/absolute/path/to/clang \
WASM_LD=/absolute/path/to/wasm-ld \
extension/wasm/scripts/build-wasm.sh

CAPTCHA_SOLVER_ALLOW_PENDING_TOOLCHAIN=1 \
EMCC=/absolute/path/to/emcc \
extension/wasm/scripts/build-wasm.sh
```

On success the script emits the `.wasm` outside the source tree and an adjacent
`.build.json` containing:

- artifact, C source, and ABI header SHA-256 digests;
- actual compiler path and version;
- fixed memory size and algorithm ID;
- the reproducible experimental command;
- explicit `containsOpenCv/containsImageCodecs/containsOnnx: false` fields.

No checked-in `.wasm` is supplied.

## Fail-closed JavaScript loader

`loader/captcha-solver-loader.mjs` accepts in-memory WASM bytes plus a trusted
SHA-256 from the experimental package manifest. It rejects imports, ABI drift,
buffer overlap, non-fixed 16 MiB memory, memory growth, digest mismatch, and
malformed results. It exposes analysis evidence only: every response carries
`actionAuthorized: false`, `solverReadiness: PENDING`, and
`opencvParity: false`; it has no URL fetch or drag API.

The loader and WASM are intentionally absent from `extension/release-files.txt`
while the extension build config is `NOT_READY`. The production extension CSP
therefore does not enable WASM evaluation. A future integration requires a
separate reviewed readiness, CSP, package-digest, and action-authorization
change; merely producing this experimental module is insufficient.

## Deterministic unsigned review package

After an experimental build, create and verify a review-only ZIP outside the
source tree:

```sh
python3 extension/wasm/scripts/package-experimental.py build \
  --wasm /absolute/path/captcha_solver.wasm \
  --metadata /absolute/path/captcha_solver.wasm.build.json \
  --loader extension/wasm/loader/captcha-solver-loader.mjs \
  --output /private/tmp/captcha_solver-experimental.zip

python3 extension/wasm/scripts/package-experimental.py verify \
  --package /private/tmp/captcha_solver-experimental.zip
```

The ZIP uses fixed metadata and stored entries. Its canonical manifest says
`EXPERIMENTAL_UNSIGNED`, `signed: false`, `solverReadiness: PENDING`,
`actionAuthorized: false`, and `opencvParity: false`. It deliberately excludes
absolute compiler paths while retaining compiler versions and source/header,
loader, and WASM hashes.

## Run all locally available tests

```sh
extension/wasm/scripts/test.sh
```

This runs the native fixture, checks the Node/loader scripts, verifies that the formal
lock fails closed, then tries two experimental WASM builds. If no wasm32 compiler
exists, it reports `EXPERIMENTAL_NOT_EXECUTED` after verifying that no artifact
was produced. That status is not a formal gate success; the formal build remains
a failure while the lock is `PENDING`. If a compiler exists, the suite requires
byte-identical WASM and review ZIPs, instantiates the actual module, compares the
full fixed-point result against the native C fixture, and repeats success,
determinism, ABSTAIN, invalid-config, and work-limit tests.

An already-built experimental module can be tested directly:

```sh
node extension/wasm/tests/test_wasm.mjs /absolute/path/to/captcha_solver.wasm
```

## Formal OpenCV/Emscripten path

`toolchain-lock.json` is the machine-readable release gate. `PENDING` is an
explicit rejection state, not a wildcard. The verifier requires canonical
sorted JSON, an exact schema with no unknown fields, and therefore also rejects
duplicate keys and alternate encodings. The formal verifier additionally requires:

- solver readiness `VERIFIED` and `formalBuildAllowed: true`;
- fixed Emscripten version and SDK manifest SHA-256;
- OpenCV 5.0.0 source archive SHA-256 and `BUILT_VERIFIED` status;
- selected libjpeg-turbo, libpng, and libwebp versions and archive hashes;
- reviewed core source/header/artifact hashes;
- a separately implemented and reviewed OpenCV/codec adapter.

Check the current gate with:

```sh
node extension/wasm/scripts/verify-formal-lock.mjs
```

or request the deliberately unavailable formal profile:

```sh
CAPTCHA_SOLVER_BUILD_PROFILE=formal-opencv \
extension/wasm/scripts/build-wasm.sh
```

Both commands must fail while any value is PENDING or any integration is
`NOT_BUILT`. Even after the lock is populated, `build-wasm.sh` still refuses the
formal profile until the separate OpenCV/codec adapter exists; this prevents a
minimal Canny-like build from being mislabeled as formal OpenCV compatibility.

## Required compatibility work before verification

1. Build a signed golden corpus containing decoded RGB, grayscale, edge-map,
   score, top-1/top-2, evidence, and final decision fixtures.
2. Include transparent PNG, ICC JPEG, WebP, odd dimensions, ties, constant
   templates, threshold boundaries, and maximum-work cases.
3. Compare native pinned ddddocr/OpenCV and browser outputs. Coordinates and
   decisions must be exact; every float tolerance must be explicit and must
   abstain at a threshold boundary.
4. Keep WASM in an isolated extension worker. Never trust page-world glue,
   page-provided policy, or page-fetched cross-origin pixels.
5. Pin and hash every source archive, toolchain manifest, command, output, and
   third-party notice before changing readiness to VERIFIED.
