#ifndef CAPTCHA_SAFE_WASM_CAPTCHA_SOLVER_H
#define CAPTCHA_SAFE_WASM_CAPTCHA_SOLVER_H

/*
 * Captcha-safe auditable matcher ABI v1.
 *
 * The core accepts already-decoded, tightly packed RGB8 pixels.  It does not
 * contain an image codec, OpenCV, ONNX, networking, browser automation, or a
 * drag implementation.  All public ABI fields are fixed-width 32-bit values
 * so a WebAssembly host can read them with a little-endian DataView.
 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CAPTCHA_SOLVER_ABI_VERSION 1u

#define CAPTCHA_SOLVER_MAX_TARGET_WIDTH 256u
#define CAPTCHA_SOLVER_MAX_TARGET_HEIGHT 256u
#define CAPTCHA_SOLVER_MAX_BACKGROUND_WIDTH 1024u
#define CAPTCHA_SOLVER_MAX_BACKGROUND_HEIGHT 512u
#define CAPTCHA_SOLVER_MAX_TARGET_PIXELS 65536u
#define CAPTCHA_SOLVER_MAX_BACKGROUND_PIXELS 524288u
#define CAPTCHA_SOLVER_TARGET_RGB_CAPACITY 196608u
#define CAPTCHA_SOLVER_BACKGROUND_RGB_CAPACITY 1572864u
#define CAPTCHA_SOLVER_COMPILED_MAX_NCC_WORK 200000000u

#define CAPTCHA_SOLVER_Q30_ONE 1073741824
#define CAPTCHA_SOLVER_Q20_ONE 1048576u

enum CaptchaSolverReturnCode {
    CAPTCHA_SOLVER_COMPLETED = 0,
    CAPTCHA_SOLVER_ERR_INVALID_DIMENSIONS = -1,
    CAPTCHA_SOLVER_ERR_INVALID_CONFIG = -2,
    CAPTCHA_SOLVER_ERR_WORK_LIMIT = -3,
    CAPTCHA_SOLVER_ERR_INTERNAL = -4,
    CAPTCHA_SOLVER_ERR_INVALID_INPUT_LENGTH = -5
};

enum CaptchaSolverDecision {
    CAPTCHA_SOLVER_DECISION_NONE = 0,
    CAPTCHA_SOLVER_DECISION_MATCH = 1,
    CAPTCHA_SOLVER_DECISION_ABSTAIN = 2,
    CAPTCHA_SOLVER_DECISION_ERROR = 3
};

enum CaptchaSolverReason {
    CAPTCHA_SOLVER_REASON_NONE = 0,
    CAPTCHA_SOLVER_REASON_LOW_TARGET_TEXTURE = 1,
    CAPTCHA_SOLVER_REASON_LOW_BACKGROUND_TEXTURE = 2,
    CAPTCHA_SOLVER_REASON_LOW_TARGET_EDGE_DENSITY = 3,
    CAPTCHA_SOLVER_REASON_LOW_BACKGROUND_EDGE_DENSITY = 4,
    CAPTCHA_SOLVER_REASON_DEGENERATE_TARGET_EDGE = 5,
    CAPTCHA_SOLVER_REASON_LOW_CONFIDENCE = 6,
    CAPTCHA_SOLVER_REASON_AMBIGUOUS_PEAK = 7,
    CAPTCHA_SOLVER_REASON_LOW_PEAK_SIGNIFICANCE = 8,
    CAPTCHA_SOLVER_REASON_LOW_LOCAL_SHARPNESS = 9,

    CAPTCHA_SOLVER_REASON_INVALID_DIMENSIONS = 100,
    CAPTCHA_SOLVER_REASON_INVALID_CONFIG = 101,
    CAPTCHA_SOLVER_REASON_WORK_LIMIT = 102,
    CAPTCHA_SOLVER_REASON_INTERNAL = 103,
    CAPTCHA_SOLVER_REASON_INVALID_INPUT_LENGTH = 104
};

/* Exactly 56 bytes in ABI v1. */
typedef struct CaptchaSolverConfigV1 {
    uint32_t abi_version;
    uint32_t struct_size;
    uint32_t canny_low_threshold;
    uint32_t canny_high_threshold;
    int32_t min_confidence_q30;
    uint32_t min_peak_gap_q30;
    uint32_t min_peak_significance_q20;
    uint32_t min_target_texture_q20;
    uint32_t min_background_texture_q20;
    uint32_t min_target_edge_density_q20;
    uint32_t min_background_edge_density_q20;
    uint32_t min_local_sharpness_q20;
    uint32_t peak_exclusion_radius_permille;
    uint32_t max_ncc_work;
} CaptchaSolverConfigV1;

/* Exactly 112 bytes in ABI v1. */
typedef struct CaptchaSolverResultV1 {
    uint32_t abi_version;
    uint32_t struct_size;
    uint32_t decision;
    uint32_t reason;
    uint32_t target_center_x;
    uint32_t target_center_y;
    uint32_t target_left;
    uint32_t target_top;
    int32_t confidence_q30;
    int32_t top1_q30;
    int32_t top2_q30;
    uint32_t peak_gap_q30;
    uint32_t peak_significance_q20;
    uint32_t target_texture_q20;
    uint32_t background_texture_q20;
    uint32_t target_edge_density_q20;
    uint32_t background_edge_density_q20;
    uint32_t local_sharpness_q20;
    uint32_t target_canny_edge_count;
    uint32_t background_canny_edge_count;
    uint32_t candidate_count;
    uint32_t ncc_work;
    uint32_t target_width;
    uint32_t target_height;
    uint32_t background_width;
    uint32_t background_height;
    uint32_t reserved0;
    uint32_t reserved1;
} CaptchaSolverResultV1;

uint32_t solver_abi_version(void);
uint32_t solver_config_size(void);
uint32_t solver_result_size(void);
uint32_t solver_target_rgb_capacity(void);
uint32_t solver_background_rgb_capacity(void);

uint8_t *solver_target_rgb(void);
uint8_t *solver_background_rgb(void);
CaptchaSolverConfigV1 *solver_config(void);
const CaptchaSolverResultV1 *solver_result(void);

/* Restore the immutable ABI defaults and clear the last result. */
void solver_reset(void);

/*
 * Execute one bounded match.  A return value of CAPTCHA_SOLVER_COMPLETED means
 * the result contains either MATCH or ABSTAIN.  Negative returns are controlled
 * input/config/resource failures and set result.decision to ERROR.
 */
int32_t solver_solve(
    uint32_t target_width,
    uint32_t target_height,
    uint32_t background_width,
    uint32_t background_height,
    uint32_t target_rgb_bytes,
    uint32_t background_rgb_bytes
);

#ifdef __cplusplus
}
#endif

#endif
