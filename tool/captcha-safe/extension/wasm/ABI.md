# Captcha Solver WASM ABI v1

Status: **fixed development ABI; solver readiness remains `PENDING`**.

The ABI accepts decoded RGB8 pixels only. It does not accept PNG, JPEG, WebP,
RGBA, URLs, DOM elements, or row padding. It does not perform a drag or produce
a verification token. Even `MATCH` is evidence only and can never authorize or
enable a drag; an external verified readiness and authorization gate must remain
closed while this solver is PENDING.

## Host protocol

1. Instantiate a module with exactly one non-growing memory.
2. Require `solver_abi_version() == 1`, `solver_config_size() == 56`, and
   `solver_result_size() == 112`.
3. Call `solver_reset()` before the first solve and before changing policy.
4. Copy exactly `target_width * target_height * 3` bytes to the address returned
   by `solver_target_rgb()` and the equivalent background bytes to
   `solver_background_rgb()`.
5. Optionally write a trusted, signed policy to the config structure. Never copy
   policy fields from page-controlled input.
6. Call `solver_solve(target_width, target_height, background_width,
   background_height, target_rgb_bytes, background_rgb_bytes)`. Both byte
   lengths must equal `width * height * 3`; declared short or long inputs are
   rejected. The host must still overwrite every byte in both exact ranges,
   because a stale byte paired with a falsely exact length cannot be detected by
   an in-memory ABI.
7. A return of `0` means the result is complete and its decision is either
   `MATCH` or `ABSTAIN`. A negative return is a controlled `ERROR`; no coordinate
   may be consumed.
8. Read exactly 112 bytes from `solver_result()`, then verify its ABI version,
   size, decision, and reason before reading coordinates.

All fields are 32-bit and WebAssembly little-endian. The implementation is
single-instance, non-reentrant, and not thread-safe. A worker must serialize
calls or instantiate one module per worker.

The checked-in experimental loader additionally requires a trusted lowercase
SHA-256 digest, zero module imports, non-growing 16 MiB memory, non-overlapping
ABI buffers, and exact result invariants. Its output always states
`actionAuthorized: false`; even a `MATCH` remains analysis evidence only.

## Exports

| Export | Result |
| --- | --- |
| `solver_abi_version()` | `1` |
| `solver_config_size()` | `56` |
| `solver_result_size()` | `112` |
| `solver_target_rgb_capacity()` | `196608` bytes |
| `solver_background_rgb_capacity()` | `1572864` bytes |
| `solver_target_rgb()` | pointer to writable target RGB8 buffer |
| `solver_background_rgb()` | pointer to writable background RGB8 buffer |
| `solver_config()` | pointer to writable 56-byte policy structure |
| `solver_result()` | pointer to read-only-by-contract 112-byte result |
| `solver_reset()` | reset policy defaults and clear result |
| `solver_solve(tw, th, bw, bh, target_bytes, background_bytes)` | `0` or a negative controlled error |

## Compile-time limits

| Limit | Value |
| --- | ---: |
| Target width × height | at most `256 × 256` |
| Target pixels | at most `65,536` |
| Background width × height | at most `1024 × 512` |
| Background pixels | at most `524,288` |
| RGB target bytes | `196,608` |
| RGB background bytes | `1,572,864` |
| Compiled NCC work | at most `200,000,000` edge comparisons |
| Development default NCC work | `100,000,000` edge comparisons |
| WASM linear memory | exactly `16,777,216` bytes; growth disabled |

All dimensions must be at least 3, and the target must fit inside the
background. The runtime work bound is `candidate_count * target_canny_edge_count`.
Exceeding any bound is an error, not an attempt to allocate more memory.

## Fixed-point representation

- Signed Q30 uses `2^30 == 1.0`. Confidence, top-1, and top-2 are in `[-1, 1]`.
- Unsigned Q30 is used for peak gap and can represent `[0, 2]`.
- Unsigned Q20 uses `2^20 == 1.0`. Peak significance may exceed one; density,
  texture, and sharpness are capped at one.

## `CaptchaSolverConfigV1` layout

| Offset | Type | Field | Reset value |
| ---: | --- | --- | ---: |
| 0 | `u32` | `abi_version` | 1 |
| 4 | `u32` | `struct_size` | 56 |
| 8 | `u32` | `canny_low_threshold` | 50 |
| 12 | `u32` | `canny_high_threshold` | 150 |
| 16 | `i32 Q30` | `min_confidence_q30` | 0.5 |
| 20 | `u32 Q30` | `min_peak_gap_q30` | 0.02 |
| 24 | `u32 Q20` | `min_peak_significance_q20` | 2.5 |
| 28 | `u32 Q20` | `min_target_texture_q20` | 0.03 |
| 32 | `u32 Q20` | `min_background_texture_q20` | 0.01 |
| 36 | `u32 Q20` | `min_target_edge_density_q20` | 0.02 |
| 40 | `u32 Q20` | `min_background_edge_density_q20` | 0.004 |
| 44 | `u32 Q20` | `min_local_sharpness_q20` | 0.002 |
| 48 | `u32` | `peak_exclusion_radius_permille` | 350 |
| 52 | `u32` | `max_ncc_work` | 100,000,000 |

Config validation is fail-closed. Thresholds must be finite by construction,
within their documented fixed-point ranges, low Canny must be less than high,
the exclusion radius must be at most 1000 permille, and work cannot exceed the
compiled limit.

## `CaptchaSolverResultV1` layout

| Offset | Type | Field |
| ---: | --- | --- |
| 0 | `u32` | `abi_version` |
| 4 | `u32` | `struct_size` |
| 8 | `u32` | `decision` |
| 12 | `u32` | `reason` |
| 16 | `u32` | `target_center_x` |
| 20 | `u32` | `target_center_y` |
| 24 | `u32` | `target_left` |
| 28 | `u32` | `target_top` |
| 32 | `i32 Q30` | `confidence_q30` |
| 36 | `i32 Q30` | `top1_q30` |
| 40 | `i32 Q30` | `top2_q30` |
| 44 | `u32 Q30` | `peak_gap_q30` |
| 48 | `u32 Q20` | `peak_significance_q20` |
| 52 | `u32 Q20` | `target_texture_q20` |
| 56 | `u32 Q20` | `background_texture_q20` |
| 60 | `u32 Q20` | `target_edge_density_q20` |
| 64 | `u32 Q20` | `background_edge_density_q20` |
| 68 | `u32 Q20` | `local_sharpness_q20` |
| 72 | `u32` | `target_canny_edge_count` |
| 76 | `u32` | `background_canny_edge_count` |
| 80 | `u32` | `candidate_count` |
| 84 | `u32` | `ncc_work` |
| 88 | `u32` | `target_width` |
| 92 | `u32` | `target_height` |
| 96 | `u32` | `background_width` |
| 100 | `u32` | `background_height` |
| 104 | `u32` | `reserved0`, must be zero |
| 108 | `u32` | `reserved1`, must be zero |

Coordinates are in original background RGB pixels. The center uses
`left + floor(target_width / 2)` and the equivalent y expression.

## Decisions, reasons, and returns

Decisions: `0 NONE`, `1 MATCH`, `2 ABSTAIN`, `3 ERROR`.

ABSTAIN reasons are evaluated in this order:

1. `1 LOW_TARGET_TEXTURE`
2. `2 LOW_BACKGROUND_TEXTURE`
3. `3 LOW_TARGET_EDGE_DENSITY`
4. `4 LOW_BACKGROUND_EDGE_DENSITY`
5. `5 DEGENERATE_TARGET_EDGE`
6. `6 LOW_CONFIDENCE`
7. `7 AMBIGUOUS_PEAK`
8. `8 LOW_PEAK_SIGNIFICANCE`
9. `9 LOW_LOCAL_SHARPNESS`

Negative returns and ERROR reasons:

| Return | Reason | Meaning |
| ---: | ---: | --- |
| `-1` | 100 | invalid or oversized dimensions |
| `-2` | 101 | invalid ABI/configuration |
| `-3` | 102 | NCC work exceeds a runtime or compile-time limit |
| `-4` | 103 | internal invariant failure |
| `-5` | 104 | RGB byte length is not exactly `width * height * 3` |

## Algorithm contract

The current core is `captcha-safe-canny-like-ncc-v1`, not OpenCV:

1. Integer RGB grayscale: `(77R + 150G + 29B + 128) >> 8`.
2. Sobel 3×3 L1 magnitude.
3. Four-direction non-maximum suppression.
4. Configured double threshold and eight-neighbour hysteresis.
5. Binary-edge `TM_CCOEFF_NORMED`-equivalent NCC.
6. First row-major maximum is top-1.
7. Top-2 is the best score outside the configured x/y exclusion radius.
8. Texture, adjacent-difference edge density, second-derivative sharpness,
   peak gap, and score-surface significance are returned as evidence.

The result is not claimed to be bit-compatible with ddddocr/OpenCV. A future
formal OpenCV/codec implementation requires a new verified toolchain lock and
golden-corpus attestation; ABI v1 may be retained only if every field preserves
these semantics.
