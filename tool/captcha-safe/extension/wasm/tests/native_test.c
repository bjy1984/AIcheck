#include "captcha_solver.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FIXTURE_TARGET_WIDTH 15u
#define FIXTURE_TARGET_HEIGHT 13u
#define FIXTURE_BACKGROUND_WIDTH 64u
#define FIXTURE_BACKGROUND_HEIGHT 40u
#define FIXTURE_LEFT 27u
#define FIXTURE_TOP 12u
#define FIXTURE_TARGET_BYTES (FIXTURE_TARGET_WIDTH * FIXTURE_TARGET_HEIGHT * 3u)
#define FIXTURE_BACKGROUND_BYTES (FIXTURE_BACKGROUND_WIDTH * FIXTURE_BACKGROUND_HEIGHT * 3u)

static void fail(const char *message) {
    fprintf(stderr, "native_test: %s\n", message);
    exit(1);
}

static void require(int condition, const char *message) {
    if (!condition) {
        fail(message);
    }
}

static void set_rgb(uint8_t *pixels, uint32_t width, uint32_t x, uint32_t y, uint8_t value) {
    uint32_t offset = (y * width + x) * 3u;
    pixels[offset] = value;
    pixels[offset + 1u] = value;
    pixels[offset + 2u] = value;
}

static void fill_rgb(uint8_t *pixels, uint32_t pixel_count, uint8_t value) {
    uint32_t index;
    for (index = 0u; index < pixel_count * 3u; ++index) {
        pixels[index] = value;
    }
}

static void build_match_fixture(void) {
    uint8_t *target = solver_target_rgb();
    uint8_t *background = solver_background_rgb();
    uint32_t x;
    uint32_t y;

    fill_rgb(target, FIXTURE_TARGET_WIDTH * FIXTURE_TARGET_HEIGHT, 128u);
    fill_rgb(background, FIXTURE_BACKGROUND_WIDTH * FIXTURE_BACKGROUND_HEIGHT, 128u);

    for (y = 1u; y + 1u < FIXTURE_TARGET_HEIGHT; ++y) {
        for (x = 1u; x + 1u < FIXTURE_TARGET_WIDTH; ++x) {
            uint32_t mixed = x * 37u + y * 53u + x * y * 11u + (x ^ y) * 17u;
            uint8_t value = (uint8_t)(24u + mixed % 208u);
            set_rgb(target, FIXTURE_TARGET_WIDTH, x, y, value);
        }
    }
    for (y = 0u; y < FIXTURE_TARGET_HEIGHT; ++y) {
        for (x = 0u; x < FIXTURE_TARGET_WIDTH; ++x) {
            uint32_t target_offset = (y * FIXTURE_TARGET_WIDTH + x) * 3u;
            uint32_t background_offset =
                ((FIXTURE_TOP + y) * FIXTURE_BACKGROUND_WIDTH + FIXTURE_LEFT + x) * 3u;
            background[background_offset] = target[target_offset];
            background[background_offset + 1u] = target[target_offset + 1u];
            background[background_offset + 2u] = target[target_offset + 2u];
        }
    }
}

static void test_abi_contract(void) {
    solver_reset();
    require(solver_abi_version() == CAPTCHA_SOLVER_ABI_VERSION, "ABI version mismatch");
    require(solver_config_size() == sizeof(CaptchaSolverConfigV1), "config size mismatch");
    require(solver_result_size() == sizeof(CaptchaSolverResultV1), "result size mismatch");
    require(
        solver_target_rgb_capacity() == CAPTCHA_SOLVER_TARGET_RGB_CAPACITY,
        "target capacity mismatch"
    );
    require(
        solver_background_rgb_capacity() == CAPTCHA_SOLVER_BACKGROUND_RGB_CAPACITY,
        "background capacity mismatch"
    );
    require(solver_config()->abi_version == CAPTCHA_SOLVER_ABI_VERSION, "config not reset");
    require(solver_result()->decision == CAPTCHA_SOLVER_DECISION_NONE, "result not cleared");
}

static CaptchaSolverResultV1 test_success_and_determinism(void) {
    CaptchaSolverResultV1 first;
    int32_t return_code;
    solver_reset();
    build_match_fixture();
    return_code = solver_solve(
        FIXTURE_TARGET_WIDTH,
        FIXTURE_TARGET_HEIGHT,
        FIXTURE_BACKGROUND_WIDTH,
        FIXTURE_BACKGROUND_HEIGHT,
        FIXTURE_TARGET_BYTES,
        FIXTURE_BACKGROUND_BYTES
    );
    require(return_code == CAPTCHA_SOLVER_COMPLETED, "fixture solve returned an error");
    if (solver_result()->decision != CAPTCHA_SOLVER_DECISION_MATCH) {
        fprintf(
            stderr,
            "fixture decision=%u reason=%u confidence=%d gap=%u significance=%u "
            "texture=(%u,%u) density=(%u,%u) sharpness=%u canny=(%u,%u) work=%u\n",
            solver_result()->decision,
            solver_result()->reason,
            solver_result()->confidence_q30,
            solver_result()->peak_gap_q30,
            solver_result()->peak_significance_q20,
            solver_result()->target_texture_q20,
            solver_result()->background_texture_q20,
            solver_result()->target_edge_density_q20,
            solver_result()->background_edge_density_q20,
            solver_result()->local_sharpness_q20,
            solver_result()->target_canny_edge_count,
            solver_result()->background_canny_edge_count,
            solver_result()->ncc_work
        );
    }
    require(solver_result()->decision == CAPTCHA_SOLVER_DECISION_MATCH, "fixture abstained");
    require(solver_result()->reason == CAPTCHA_SOLVER_REASON_NONE, "fixture has a reason");
    require(solver_result()->target_left == FIXTURE_LEFT, "fixture left coordinate changed");
    require(solver_result()->target_top == FIXTURE_TOP, "fixture top coordinate changed");
    require(
        solver_result()->target_center_x == FIXTURE_LEFT + FIXTURE_TARGET_WIDTH / 2u,
        "fixture center x changed"
    );
    require(
        solver_result()->target_center_y == FIXTURE_TOP + FIXTURE_TARGET_HEIGHT / 2u,
        "fixture center y changed"
    );
    require(solver_result()->confidence_q30 > CAPTCHA_SOLVER_Q30_ONE / 2, "low confidence");
    require(solver_result()->peak_gap_q30 > 0u, "missing peak gap");
    require(solver_result()->target_canny_edge_count > 0u, "missing target edges");
    require(solver_result()->ncc_work > 0u, "missing work accounting");
    first = *solver_result();

    return_code = solver_solve(
        FIXTURE_TARGET_WIDTH,
        FIXTURE_TARGET_HEIGHT,
        FIXTURE_BACKGROUND_WIDTH,
        FIXTURE_BACKGROUND_HEIGHT,
        FIXTURE_TARGET_BYTES,
        FIXTURE_BACKGROUND_BYTES
    );
    require(return_code == CAPTCHA_SOLVER_COMPLETED, "repeat solve returned an error");
    require(memcmp(&first, solver_result(), sizeof(first)) == 0, "result is not deterministic");
    return first;
}

static void test_abstain(void) {
    int32_t return_code;
    solver_reset();
    fill_rgb(
        solver_target_rgb(), FIXTURE_TARGET_WIDTH * FIXTURE_TARGET_HEIGHT, 128u
    );
    fill_rgb(
        solver_background_rgb(), FIXTURE_BACKGROUND_WIDTH * FIXTURE_BACKGROUND_HEIGHT, 128u
    );
    return_code = solver_solve(
        FIXTURE_TARGET_WIDTH,
        FIXTURE_TARGET_HEIGHT,
        FIXTURE_BACKGROUND_WIDTH,
        FIXTURE_BACKGROUND_HEIGHT,
        FIXTURE_TARGET_BYTES,
        FIXTURE_BACKGROUND_BYTES
    );
    require(return_code == CAPTCHA_SOLVER_COMPLETED, "low-texture input returned an error");
    require(
        solver_result()->decision == CAPTCHA_SOLVER_DECISION_ABSTAIN,
        "low-texture input did not abstain"
    );
    require(
        solver_result()->reason == CAPTCHA_SOLVER_REASON_LOW_TARGET_TEXTURE,
        "low-texture reason changed"
    );
}

static void test_fail_closed_errors(void) {
    int32_t return_code;

    solver_reset();
    return_code = solver_solve(
        CAPTCHA_SOLVER_MAX_TARGET_WIDTH + 1u,
        10u,
        CAPTCHA_SOLVER_MAX_BACKGROUND_WIDTH,
        20u,
        0u,
        0u
    );
    require(return_code == CAPTCHA_SOLVER_ERR_INVALID_DIMENSIONS, "oversize input accepted");
    require(solver_result()->decision == CAPTCHA_SOLVER_DECISION_ERROR, "oversize not an error");

    solver_reset();
    build_match_fixture();
    return_code = solver_solve(
        FIXTURE_TARGET_WIDTH,
        FIXTURE_TARGET_HEIGHT,
        FIXTURE_BACKGROUND_WIDTH,
        FIXTURE_BACKGROUND_HEIGHT,
        FIXTURE_TARGET_BYTES - 1u,
        FIXTURE_BACKGROUND_BYTES
    );
    require(
        return_code == CAPTCHA_SOLVER_ERR_INVALID_INPUT_LENGTH,
        "short RGB input length accepted"
    );
    require(
        solver_result()->reason == CAPTCHA_SOLVER_REASON_INVALID_INPUT_LENGTH,
        "short RGB input reason changed"
    );

    solver_reset();
    build_match_fixture();
    solver_config()->canny_high_threshold = solver_config()->canny_low_threshold;
    return_code = solver_solve(
        FIXTURE_TARGET_WIDTH,
        FIXTURE_TARGET_HEIGHT,
        FIXTURE_BACKGROUND_WIDTH,
        FIXTURE_BACKGROUND_HEIGHT,
        FIXTURE_TARGET_BYTES,
        FIXTURE_BACKGROUND_BYTES
    );
    require(return_code == CAPTCHA_SOLVER_ERR_INVALID_CONFIG, "invalid config accepted");
    require(
        solver_result()->reason == CAPTCHA_SOLVER_REASON_INVALID_CONFIG,
        "invalid config reason changed"
    );

    solver_reset();
    build_match_fixture();
    solver_config()->max_ncc_work = 1u;
    return_code = solver_solve(
        FIXTURE_TARGET_WIDTH,
        FIXTURE_TARGET_HEIGHT,
        FIXTURE_BACKGROUND_WIDTH,
        FIXTURE_BACKGROUND_HEIGHT,
        FIXTURE_TARGET_BYTES,
        FIXTURE_BACKGROUND_BYTES
    );
    require(return_code == CAPTCHA_SOLVER_ERR_WORK_LIMIT, "work limit not enforced");
    require(
        solver_result()->reason == CAPTCHA_SOLVER_REASON_WORK_LIMIT,
        "work-limit reason changed"
    );
}

static void print_consistency_vector(const CaptchaSolverResultV1 *result) {
    printf(
        "NATIVE_VECTOR_JSON "
        "{\"abiVersion\":%u,\"structSize\":%u,\"decision\":%u,\"reason\":%u,"
        "\"centerX\":%u,\"centerY\":%u,\"left\":%u,\"top\":%u,"
        "\"confidenceQ30\":%d,\"top1Q30\":%d,\"top2Q30\":%d,"
        "\"peakGapQ30\":%u,\"peakSignificanceQ20\":%u,"
        "\"targetTextureQ20\":%u,\"backgroundTextureQ20\":%u,"
        "\"targetEdgeDensityQ20\":%u,\"backgroundEdgeDensityQ20\":%u,"
        "\"localSharpnessQ20\":%u,\"targetCannyEdgeCount\":%u,"
        "\"backgroundCannyEdgeCount\":%u,\"candidateCount\":%u,\"nccWork\":%u,"
        "\"targetWidth\":%u,\"targetHeight\":%u,\"backgroundWidth\":%u,"
        "\"backgroundHeight\":%u,\"reserved0\":%u,\"reserved1\":%u}\n",
        result->abi_version,
        result->struct_size,
        result->decision,
        result->reason,
        result->target_center_x,
        result->target_center_y,
        result->target_left,
        result->target_top,
        result->confidence_q30,
        result->top1_q30,
        result->top2_q30,
        result->peak_gap_q30,
        result->peak_significance_q20,
        result->target_texture_q20,
        result->background_texture_q20,
        result->target_edge_density_q20,
        result->background_edge_density_q20,
        result->local_sharpness_q20,
        result->target_canny_edge_count,
        result->background_canny_edge_count,
        result->candidate_count,
        result->ncc_work,
        result->target_width,
        result->target_height,
        result->background_width,
        result->background_height,
        result->reserved0,
        result->reserved1
    );
}

int main(void) {
    CaptchaSolverResultV1 result;
    test_abi_contract();
    result = test_success_and_determinism();
    test_abstain();
    test_fail_closed_errors();
    printf(
        "native solver tests passed: center=(%u,%u) confidence_q30=%d "
        "gap_q30=%u significance_q20=%u work=%u\n",
        result.target_center_x,
        result.target_center_y,
        result.confidence_q30,
        result.peak_gap_q30,
        result.peak_significance_q20,
        result.ncc_work
    );
    print_consistency_vector(&result);
    return 0;
}
