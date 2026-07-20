# MV3 CSP patch

The official 4.13.0 documentation artifact has an embedded WASM payload, but
its older Emscripten glue contains four JavaScript `Function` constructor
paths.
Chrome MV3's `wasm-unsafe-eval` CSP token permits WebAssembly compilation; it
does not permit dynamic JavaScript compilation.

The deterministic `patch-mv3.mjs` transformation makes four scoped changes:

1. Embind's diagnostic named-function helper now creates a normal closure and
   assigns its display name with `Object.defineProperty` when supported.
2. Embind's function-pointer adapter now forwards `arguments` through a normal
   closure and `Function.prototype.apply`.
3. Embind's generated C++ invocation wrapper now uses the closure-based
   marshalling path equivalent to Emscripten's `DYNAMIC_EXECUTION=0` fallback.
4. Emval method callers now decode wire arguments and invoke the target through
   a normal closure.

The last two replacements follow the behavior of Emscripten's documented
`DYNAMIC_EXECUTION=0` closure fallbacks (the 2.0.10 `embind.js` and `emval.js`
implementations), without claiming that OpenCV's published artifact exposes an
exact Emscripten version.

Neither change alters the native WASM bytes, image processing operations, or
public OpenCV.js API. The script requires the exact upstream SHA-256 and checks
the exact patched SHA-256, and it fails unless both patch anchors are unique.

To reproduce:

```sh
curl -fsSL https://docs.opencv.org/4.13.0/opencv.js -o /tmp/opencv-4.13.0.js
node patch-mv3.mjs /tmp/opencv-4.13.0.js
shasum -a 256 /tmp/opencv-4.13.0.js
```

The resulting digest must be
`67b747b73392a012ad7af59adaef2bf1a1606a843ab75ece4ec19da981bd2138`.
