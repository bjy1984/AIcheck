# Bundled OpenCV.js

This directory vendors the official OpenCV 4.13.0 documentation build from
`https://docs.opencv.org/4.13.0/opencv.js`. The build is a classic script whose
WebAssembly payload is embedded as a data URI, so loading it performs no
runtime code fetch. Four Emscripten compatibility paths in the upstream file
used the JavaScript `Function` constructor, including the Embind invocation
generator reached during runtime registration. `patch-mv3.mjs`
deterministically replaces them with closure-based equivalents so the artifact
is compatible with an MV3 `script-src 'self' 'wasm-unsafe-eval'` policy.

`solver/offscreen.html` loads `opencv.js` as a classic script before loading
the module-based adapter. The adapter waits for the OpenCV thenable to report
runtime initialization without resolving a JavaScript Promise with that
thenable object.

`lock.json` records both the upstream and patched sizes and SHA-256 values.
OpenCV's license is preserved in `LICENSE`. The official artifact does not
publish its Emscripten version, so the lock deliberately records that value as
`null` rather than guessing a toolchain version. See `PATCHES.md` for the patch
rationale and reproduction procedure.
