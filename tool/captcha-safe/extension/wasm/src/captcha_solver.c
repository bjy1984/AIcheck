#include "captcha_solver.h"

#include <stddef.h>

#if defined(__GNUC__) || defined(__clang__)
#define SOLVER_EXPORT __attribute__((visibility("default"), used))
#else
#define SOLVER_EXPORT
#endif

#define SOLVER_DEFAULT_MAX_NCC_WORK 100000000u
#define SOLVER_MAX_SOBEL_MAGNITUDE 2040u
#define SOLVER_MAX_PEAK_SIGNIFICANCE_Q20 (64u * CAPTCHA_SOLVER_Q20_ONE)
#define SOLVER_EDGE_EVIDENCE_THRESHOLD 16u
#define SOLVER_INTEGRAL_CAPACITY \
    ((CAPTCHA_SOLVER_MAX_BACKGROUND_WIDTH + 1u) * \
     (CAPTCHA_SOLVER_MAX_BACKGROUND_HEIGHT + 1u))

_Static_assert(sizeof(CaptchaSolverConfigV1) == 56u, "config ABI drift");
_Static_assert(sizeof(CaptchaSolverResultV1) == 112u, "result ABI drift");
_Static_assert(offsetof(CaptchaSolverResultV1, confidence_q30) == 32u,
               "result score offset drift");
_Static_assert(offsetof(CaptchaSolverResultV1, target_width) == 88u,
               "result dimension offset drift");

typedef struct SolverEvidence {
    uint32_t texture_q20;
    uint32_t edge_density_q20;
    uint32_t sharpness_q20;
} SolverEvidence;

typedef union SolverQueueOrScores {
    uint32_t queue[CAPTCHA_SOLVER_MAX_BACKGROUND_PIXELS];
    float scores[CAPTCHA_SOLVER_MAX_BACKGROUND_PIXELS];
} SolverQueueOrScores;

typedef union SolverMagnitudeOrPositions {
    uint16_t magnitude[CAPTCHA_SOLVER_MAX_BACKGROUND_PIXELS];
    uint32_t target_positions[CAPTCHA_SOLVER_MAX_TARGET_PIXELS];
} SolverMagnitudeOrPositions;

static uint8_t g_target_rgb[CAPTCHA_SOLVER_TARGET_RGB_CAPACITY];
static uint8_t g_background_rgb[CAPTCHA_SOLVER_BACKGROUND_RGB_CAPACITY];
static uint8_t g_target_gray[CAPTCHA_SOLVER_MAX_TARGET_PIXELS];
static uint8_t g_background_gray[CAPTCHA_SOLVER_MAX_BACKGROUND_PIXELS];
static uint8_t g_target_edges[CAPTCHA_SOLVER_MAX_TARGET_PIXELS];
static uint8_t g_background_edges[CAPTCHA_SOLVER_MAX_BACKGROUND_PIXELS];
static SolverQueueOrScores g_queue_or_scores;
static SolverMagnitudeOrPositions g_magnitude_or_positions;
static uint32_t g_background_integral[SOLVER_INTEGRAL_CAPACITY];
static CaptchaSolverConfigV1 g_config;
static CaptchaSolverResultV1 g_result;

static void solver_zero_u8(uint8_t *buffer, uint32_t count) {
    uint32_t index;
    for (index = 0u; index < count; ++index) {
        buffer[index] = 0u;
    }
}

static void solver_zero_u32(uint32_t *buffer, uint32_t count) {
    uint32_t index;
    for (index = 0u; index < count; ++index) {
        buffer[index] = 0u;
    }
}

static double solver_sqrt(double value) {
    if (value <= 0.0) {
        return 0.0;
    }
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_sqrt(value);
#else
    {
        double estimate = value >= 1.0 ? value : 1.0;
        uint32_t iteration;
        for (iteration = 0u; iteration < 64u; ++iteration) {
            estimate = 0.5 * (estimate + value / estimate);
        }
        return estimate;
    }
#endif
}

static uint32_t solver_abs_i32(int32_t value) {
    return (uint32_t)(value < 0 ? -value : value);
}

static uint32_t solver_q20(double value, double maximum) {
    double scaled;
    if (value <= 0.0) {
        return 0u;
    }
    if (value >= maximum) {
        value = maximum;
    }
    scaled = value * (double)CAPTCHA_SOLVER_Q20_ONE;
    if (scaled >= 4294967295.0) {
        return 0xffffffffu;
    }
    return (uint32_t)(scaled + 0.5);
}

static int32_t solver_score_q30(double value) {
    double scaled;
    if (value <= -1.0) {
        return -CAPTCHA_SOLVER_Q30_ONE;
    }
    if (value >= 1.0) {
        return CAPTCHA_SOLVER_Q30_ONE;
    }
    scaled = value * (double)CAPTCHA_SOLVER_Q30_ONE;
    return (int32_t)(scaled >= 0.0 ? scaled + 0.5 : scaled - 0.5);
}

static uint32_t solver_gap_q30(double value) {
    double scaled;
    if (value <= 0.0) {
        return 0u;
    }
    if (value >= 2.0) {
        return 2u * (uint32_t)CAPTCHA_SOLVER_Q30_ONE;
    }
    scaled = value * (double)CAPTCHA_SOLVER_Q30_ONE;
    return (uint32_t)(scaled + 0.5);
}

static uint32_t solver_round_ratio_even(uint32_t numerator, uint32_t denominator) {
    uint32_t quotient = numerator / denominator;
    uint32_t remainder = numerator % denominator;
    uint32_t doubled = remainder * 2u;
    if (doubled > denominator || (doubled == denominator && (quotient & 1u) != 0u)) {
        ++quotient;
    }
    return quotient;
}

static void solver_clear_result(void) {
    solver_zero_u8((uint8_t *)(void *)&g_result, (uint32_t)sizeof(g_result));
    g_result.abi_version = CAPTCHA_SOLVER_ABI_VERSION;
    g_result.struct_size = (uint32_t)sizeof(g_result);
}

static int32_t solver_fail(int32_t code, uint32_t reason) {
    g_result.decision = CAPTCHA_SOLVER_DECISION_ERROR;
    g_result.reason = reason;
    return code;
}

static int32_t solver_abstain(uint32_t reason) {
    g_result.decision = CAPTCHA_SOLVER_DECISION_ABSTAIN;
    g_result.reason = reason;
    return CAPTCHA_SOLVER_COMPLETED;
}

static int solver_dimensions_valid(
    uint32_t target_width,
    uint32_t target_height,
    uint32_t background_width,
    uint32_t background_height
) {
    uint64_t target_pixels;
    uint64_t background_pixels;
    if (target_width < 3u || target_height < 3u || background_width < 3u ||
        background_height < 3u) {
        return 0;
    }
    if (target_width > CAPTCHA_SOLVER_MAX_TARGET_WIDTH ||
        target_height > CAPTCHA_SOLVER_MAX_TARGET_HEIGHT ||
        background_width > CAPTCHA_SOLVER_MAX_BACKGROUND_WIDTH ||
        background_height > CAPTCHA_SOLVER_MAX_BACKGROUND_HEIGHT ||
        target_width > background_width || target_height > background_height) {
        return 0;
    }
    target_pixels = (uint64_t)target_width * (uint64_t)target_height;
    background_pixels = (uint64_t)background_width * (uint64_t)background_height;
    return target_pixels <= CAPTCHA_SOLVER_MAX_TARGET_PIXELS &&
           background_pixels <= CAPTCHA_SOLVER_MAX_BACKGROUND_PIXELS;
}

static int solver_config_valid(void) {
    uint64_t max_gap_q30 = 2ull * (uint64_t)CAPTCHA_SOLVER_Q30_ONE;
    return g_config.abi_version == CAPTCHA_SOLVER_ABI_VERSION &&
           g_config.struct_size == sizeof(g_config) &&
           g_config.canny_low_threshold > 0u &&
           g_config.canny_low_threshold < g_config.canny_high_threshold &&
           g_config.canny_high_threshold <= SOLVER_MAX_SOBEL_MAGNITUDE &&
           g_config.min_confidence_q30 >= 0 &&
           g_config.min_confidence_q30 <= CAPTCHA_SOLVER_Q30_ONE &&
           (uint64_t)g_config.min_peak_gap_q30 <= max_gap_q30 &&
           g_config.min_peak_significance_q20 <= SOLVER_MAX_PEAK_SIGNIFICANCE_Q20 &&
           g_config.min_target_texture_q20 <= CAPTCHA_SOLVER_Q20_ONE &&
           g_config.min_background_texture_q20 <= CAPTCHA_SOLVER_Q20_ONE &&
           g_config.min_target_edge_density_q20 <= CAPTCHA_SOLVER_Q20_ONE &&
           g_config.min_background_edge_density_q20 <= CAPTCHA_SOLVER_Q20_ONE &&
           g_config.min_local_sharpness_q20 <= CAPTCHA_SOLVER_Q20_ONE &&
           g_config.peak_exclusion_radius_permille <= 1000u &&
           g_config.max_ncc_work > 0u &&
           g_config.max_ncc_work <= CAPTCHA_SOLVER_COMPILED_MAX_NCC_WORK;
}

static void solver_rgb_to_gray(const uint8_t *rgb, uint8_t *gray, uint32_t pixels) {
    uint32_t index;
    for (index = 0u; index < pixels; ++index) {
        uint32_t offset = index * 3u;
        uint32_t red = rgb[offset];
        uint32_t green = rgb[offset + 1u];
        uint32_t blue = rgb[offset + 2u];
        gray[index] = (uint8_t)((77u * red + 150u * green + 29u * blue + 128u) >> 8u);
    }
}

static void solver_sobel(
    const uint8_t *gray,
    uint32_t width,
    uint32_t index,
    int32_t *gradient_x,
    int32_t *gradient_y
) {
    int32_t upper_left = gray[index - width - 1u];
    int32_t upper = gray[index - width];
    int32_t upper_right = gray[index - width + 1u];
    int32_t left = gray[index - 1u];
    int32_t right = gray[index + 1u];
    int32_t lower_left = gray[index + width - 1u];
    int32_t lower = gray[index + width];
    int32_t lower_right = gray[index + width + 1u];
    *gradient_x = -upper_left + upper_right - 2 * left + 2 * right - lower_left + lower_right;
    *gradient_y = -upper_left - 2 * upper - upper_right + lower_left + 2 * lower +
                  lower_right;
}

/*
 * Deliberately labelled Canny-like: Sobel L1 magnitude, four-bin non-maximum
 * suppression, double threshold, and eight-neighbour hysteresis.  No Gaussian
 * codec/preprocessing or claim of OpenCV bit compatibility is made.
 */
static uint32_t solver_canny_like(
    const uint8_t *gray,
    uint32_t width,
    uint32_t height,
    uint8_t *edges
) {
    uint32_t pixels = width * height;
    uint16_t *magnitude = g_magnitude_or_positions.magnitude;
    uint32_t *queue = g_queue_or_scores.queue;
    uint32_t x;
    uint32_t y;
    uint32_t head = 0u;
    uint32_t tail = 0u;
    uint32_t count = 0u;

    solver_zero_u8(edges, pixels);
    for (x = 0u; x < pixels; ++x) {
        magnitude[x] = 0u;
    }

    for (y = 1u; y + 1u < height; ++y) {
        for (x = 1u; x + 1u < width; ++x) {
            uint32_t index = y * width + x;
            int32_t gradient_x;
            int32_t gradient_y;
            uint32_t value;
            solver_sobel(gray, width, index, &gradient_x, &gradient_y);
            value = solver_abs_i32(gradient_x) + solver_abs_i32(gradient_y);
            magnitude[index] = (uint16_t)value;
        }
    }

    for (y = 1u; y + 1u < height; ++y) {
        for (x = 1u; x + 1u < width; ++x) {
            uint32_t index = y * width + x;
            uint32_t value = magnitude[index];
            uint32_t neighbour_a;
            uint32_t neighbour_b;
            int32_t gradient_x;
            int32_t gradient_y;
            uint32_t abs_x;
            uint32_t abs_y;
            if (value < g_config.canny_low_threshold) {
                continue;
            }
            solver_sobel(gray, width, index, &gradient_x, &gradient_y);
            abs_x = solver_abs_i32(gradient_x);
            abs_y = solver_abs_i32(gradient_y);
            if (abs_y * 1000u <= abs_x * 414u) {
                neighbour_a = magnitude[index - 1u];
                neighbour_b = magnitude[index + 1u];
            } else if (abs_x * 1000u <= abs_y * 414u) {
                neighbour_a = magnitude[index - width];
                neighbour_b = magnitude[index + width];
            } else if ((gradient_x < 0) == (gradient_y < 0)) {
                neighbour_a = magnitude[index - width - 1u];
                neighbour_b = magnitude[index + width + 1u];
            } else {
                neighbour_a = magnitude[index - width + 1u];
                neighbour_b = magnitude[index + width - 1u];
            }
            if (value < neighbour_a || value < neighbour_b) {
                continue;
            }
            if (value >= g_config.canny_high_threshold) {
                edges[index] = 255u;
                queue[tail++] = index;
            } else {
                edges[index] = 128u;
            }
        }
    }

    while (head < tail) {
        uint32_t index = queue[head++];
        uint32_t center_y = index / width;
        uint32_t center_x = index - center_y * width;
        int32_t delta_y;
        int32_t delta_x;
        for (delta_y = -1; delta_y <= 1; ++delta_y) {
            for (delta_x = -1; delta_x <= 1; ++delta_x) {
                uint32_t neighbour;
                if ((delta_x == 0 && delta_y == 0) ||
                    (delta_x < 0 && center_x == 0u) ||
                    (delta_x > 0 && center_x + 1u >= width) ||
                    (delta_y < 0 && center_y == 0u) ||
                    (delta_y > 0 && center_y + 1u >= height)) {
                    continue;
                }
                neighbour = (uint32_t)((int32_t)index + delta_y * (int32_t)width + delta_x);
                if (edges[neighbour] == 128u) {
                    edges[neighbour] = 255u;
                    queue[tail++] = neighbour;
                }
            }
        }
    }

    for (x = 0u; x < pixels; ++x) {
        if (edges[x] == 255u) {
            ++count;
        } else {
            edges[x] = 0u;
        }
    }
    return count;
}

static SolverEvidence solver_evidence_region(
    const uint8_t *gray,
    uint32_t stride,
    uint32_t left,
    uint32_t top,
    uint32_t width,
    uint32_t height
) {
    SolverEvidence evidence;
    uint64_t sum = 0u;
    uint64_t square_sum = 0u;
    uint64_t edge_hits = 0u;
    uint64_t edge_comparisons = 0u;
    uint64_t second_sum = 0u;
    uint64_t second_count = 0u;
    uint32_t x;
    uint32_t y;
    uint32_t count = width * height;
    double mean;
    double variance;
    double texture;
    double edge_density;
    double sharpness;

    for (y = 0u; y < height; ++y) {
        for (x = 0u; x < width; ++x) {
            uint32_t index = (top + y) * stride + left + x;
            uint32_t center = gray[index];
            sum += center;
            square_sum += (uint64_t)center * (uint64_t)center;
            if (x + 1u < width) {
                uint32_t right = gray[index + 1u];
                ++edge_comparisons;
                edge_hits += solver_abs_i32((int32_t)center - (int32_t)right) >=
                             SOLVER_EDGE_EVIDENCE_THRESHOLD;
            }
            if (y + 1u < height) {
                uint32_t below = gray[index + stride];
                ++edge_comparisons;
                edge_hits += solver_abs_i32((int32_t)center - (int32_t)below) >=
                             SOLVER_EDGE_EVIDENCE_THRESHOLD;
            }
            if (x > 0u && x + 1u < width) {
                int32_t second = 2 * (int32_t)center - (int32_t)gray[index - 1u] -
                                 (int32_t)gray[index + 1u];
                second_sum += solver_abs_i32(second);
                ++second_count;
            }
            if (y > 0u && y + 1u < height) {
                int32_t second = 2 * (int32_t)center - (int32_t)gray[index - stride] -
                                 (int32_t)gray[index + stride];
                second_sum += solver_abs_i32(second);
                ++second_count;
            }
        }
    }

    mean = (double)sum / (double)count;
    variance = (double)square_sum / (double)count - mean * mean;
    if (variance < 0.0) {
        variance = 0.0;
    }
    texture = solver_sqrt(variance) / 127.5;
    if (texture > 1.0) {
        texture = 1.0;
    }
    edge_density = edge_comparisons > 0u
                       ? (double)edge_hits / (double)edge_comparisons
                       : 0.0;
    sharpness = second_count > 0u
                    ? (double)second_sum / (double)second_count / 255.0
                    : 0.0;
    if (sharpness > 1.0) {
        sharpness = 1.0;
    }
    evidence.texture_q20 = solver_q20(texture, 1.0);
    evidence.edge_density_q20 = solver_q20(edge_density, 1.0);
    evidence.sharpness_q20 = solver_q20(sharpness, 1.0);
    return evidence;
}

static void solver_build_integral(
    const uint8_t *edges,
    uint32_t width,
    uint32_t height
) {
    uint32_t integral_stride = width + 1u;
    uint32_t x;
    uint32_t y;
    solver_zero_u32(g_background_integral, integral_stride);
    for (y = 1u; y <= height; ++y) {
        uint32_t row_count = 0u;
        g_background_integral[y * integral_stride] = 0u;
        for (x = 1u; x <= width; ++x) {
            row_count += edges[(y - 1u) * width + x - 1u] == 255u;
            g_background_integral[y * integral_stride + x] =
                g_background_integral[(y - 1u) * integral_stride + x] + row_count;
        }
    }
}

static uint32_t solver_integral_patch_count(
    uint32_t background_width,
    uint32_t left,
    uint32_t top,
    uint32_t width,
    uint32_t height
) {
    uint32_t stride = background_width + 1u;
    uint32_t right = left + width;
    uint32_t bottom = top + height;
    return g_background_integral[bottom * stride + right] -
           g_background_integral[top * stride + right] -
           g_background_integral[bottom * stride + left] +
           g_background_integral[top * stride + left];
}

static double solver_ncc_score(
    uint32_t target_width,
    uint32_t target_height,
    uint32_t background_width,
    uint32_t left,
    uint32_t top,
    uint32_t target_edge_count
) {
    uint32_t target_pixels = target_width * target_height;
    uint32_t patch_edge_count = solver_integral_patch_count(
        background_width, left, top, target_width, target_height
    );
    uint32_t overlap = 0u;
    uint32_t position_index;
    double numerator;
    double target_variance;
    double patch_variance;
    double denominator;

    for (position_index = 0u; position_index < target_edge_count; ++position_index) {
        uint32_t packed = g_magnitude_or_positions.target_positions[position_index];
        uint32_t target_x = packed & 0xffffu;
        uint32_t target_y = packed >> 16u;
        overlap += g_background_edges[(top + target_y) * background_width + left + target_x] ==
                   255u;
    }

    numerator = (double)target_pixels * (double)overlap -
                (double)target_edge_count * (double)patch_edge_count;
    target_variance = (double)target_pixels * (double)target_edge_count -
                      (double)target_edge_count * (double)target_edge_count;
    patch_variance = (double)target_pixels * (double)patch_edge_count -
                     (double)patch_edge_count * (double)patch_edge_count;
    if (target_variance <= 0.0 || patch_variance <= 0.0) {
        return -1.0;
    }
    denominator = solver_sqrt(target_variance * patch_variance);
    if (denominator <= 0.0) {
        return -1.0;
    }
    numerator /= denominator;
    if (numerator < -1.0) {
        return -1.0;
    }
    if (numerator > 1.0) {
        return 1.0;
    }
    return numerator;
}

SOLVER_EXPORT uint32_t solver_abi_version(void) {
    return CAPTCHA_SOLVER_ABI_VERSION;
}

SOLVER_EXPORT uint32_t solver_config_size(void) {
    return (uint32_t)sizeof(g_config);
}

SOLVER_EXPORT uint32_t solver_result_size(void) {
    return (uint32_t)sizeof(g_result);
}

SOLVER_EXPORT uint32_t solver_target_rgb_capacity(void) {
    return CAPTCHA_SOLVER_TARGET_RGB_CAPACITY;
}

SOLVER_EXPORT uint32_t solver_background_rgb_capacity(void) {
    return CAPTCHA_SOLVER_BACKGROUND_RGB_CAPACITY;
}

SOLVER_EXPORT uint8_t *solver_target_rgb(void) {
    return g_target_rgb;
}

SOLVER_EXPORT uint8_t *solver_background_rgb(void) {
    return g_background_rgb;
}

SOLVER_EXPORT CaptchaSolverConfigV1 *solver_config(void) {
    return &g_config;
}

SOLVER_EXPORT const CaptchaSolverResultV1 *solver_result(void) {
    return &g_result;
}

SOLVER_EXPORT void solver_reset(void) {
    solver_zero_u8((uint8_t *)(void *)&g_config, (uint32_t)sizeof(g_config));
    g_config.abi_version = CAPTCHA_SOLVER_ABI_VERSION;
    g_config.struct_size = (uint32_t)sizeof(g_config);
    g_config.canny_low_threshold = 50u;
    g_config.canny_high_threshold = 150u;
    g_config.min_confidence_q30 = CAPTCHA_SOLVER_Q30_ONE / 2;
    g_config.min_peak_gap_q30 = 21474836u; /* round(0.02 * 2^30) */
    g_config.min_peak_significance_q20 = 2621440u; /* 2.5 * 2^20 */
    g_config.min_target_texture_q20 = 31457u; /* round(0.03 * 2^20) */
    g_config.min_background_texture_q20 = 10486u; /* round(0.01 * 2^20) */
    g_config.min_target_edge_density_q20 = 20972u; /* round(0.02 * 2^20) */
    g_config.min_background_edge_density_q20 = 4194u; /* round(0.004 * 2^20) */
    g_config.min_local_sharpness_q20 = 2097u; /* round(0.002 * 2^20) */
    g_config.peak_exclusion_radius_permille = 350u;
    g_config.max_ncc_work = SOLVER_DEFAULT_MAX_NCC_WORK;
    solver_clear_result();
}

SOLVER_EXPORT int32_t solver_solve(
    uint32_t target_width,
    uint32_t target_height,
    uint32_t background_width,
    uint32_t background_height,
    uint32_t target_rgb_bytes,
    uint32_t background_rgb_bytes
) {
    uint32_t target_pixels;
    uint32_t background_pixels;
    uint32_t target_edge_count;
    uint32_t background_edge_count;
    uint32_t positions_width;
    uint32_t positions_height;
    uint32_t candidate_count;
    uint64_t ncc_work;
    uint32_t x;
    uint32_t y;
    uint32_t candidate_index = 0u;
    uint32_t best_index = 0u;
    uint32_t best_x;
    uint32_t best_y;
    uint32_t exclusion_x;
    uint32_t exclusion_y;
    double best_score = -2.0;
    double second_score = -1.0;
    double score_sum = 0.0;
    double score_square_sum = 0.0;
    double score_mean;
    double score_variance;
    double peak_gap;
    double peak_significance;
    SolverEvidence target_evidence;
    SolverEvidence background_evidence;
    SolverEvidence matched_evidence;
    uint32_t target_sharpness;

    solver_clear_result();
    g_result.target_width = target_width;
    g_result.target_height = target_height;
    g_result.background_width = background_width;
    g_result.background_height = background_height;

    if (!solver_dimensions_valid(
            target_width, target_height, background_width, background_height
        )) {
        return solver_fail(
            CAPTCHA_SOLVER_ERR_INVALID_DIMENSIONS,
            CAPTCHA_SOLVER_REASON_INVALID_DIMENSIONS
        );
    }
    if (target_rgb_bytes != target_width * target_height * 3u ||
        background_rgb_bytes != background_width * background_height * 3u) {
        return solver_fail(
            CAPTCHA_SOLVER_ERR_INVALID_INPUT_LENGTH,
            CAPTCHA_SOLVER_REASON_INVALID_INPUT_LENGTH
        );
    }
    if (!solver_config_valid()) {
        return solver_fail(CAPTCHA_SOLVER_ERR_INVALID_CONFIG, CAPTCHA_SOLVER_REASON_INVALID_CONFIG);
    }

    target_pixels = target_width * target_height;
    background_pixels = background_width * background_height;
    solver_rgb_to_gray(g_target_rgb, g_target_gray, target_pixels);
    solver_rgb_to_gray(g_background_rgb, g_background_gray, background_pixels);

    target_evidence = solver_evidence_region(
        g_target_gray, target_width, 0u, 0u, target_width, target_height
    );
    background_evidence = solver_evidence_region(
        g_background_gray, background_width, 0u, 0u, background_width, background_height
    );
    g_result.target_texture_q20 = target_evidence.texture_q20;
    g_result.background_texture_q20 = background_evidence.texture_q20;
    g_result.target_edge_density_q20 = target_evidence.edge_density_q20;
    g_result.background_edge_density_q20 = background_evidence.edge_density_q20;

    if (target_evidence.texture_q20 < g_config.min_target_texture_q20) {
        return solver_abstain(CAPTCHA_SOLVER_REASON_LOW_TARGET_TEXTURE);
    }
    if (background_evidence.texture_q20 < g_config.min_background_texture_q20) {
        return solver_abstain(CAPTCHA_SOLVER_REASON_LOW_BACKGROUND_TEXTURE);
    }
    if (target_evidence.edge_density_q20 < g_config.min_target_edge_density_q20) {
        return solver_abstain(CAPTCHA_SOLVER_REASON_LOW_TARGET_EDGE_DENSITY);
    }
    if (background_evidence.edge_density_q20 < g_config.min_background_edge_density_q20) {
        return solver_abstain(CAPTCHA_SOLVER_REASON_LOW_BACKGROUND_EDGE_DENSITY);
    }

    target_edge_count = solver_canny_like(
        g_target_gray, target_width, target_height, g_target_edges
    );
    background_edge_count = solver_canny_like(
        g_background_gray, background_width, background_height, g_background_edges
    );
    g_result.target_canny_edge_count = target_edge_count;
    g_result.background_canny_edge_count = background_edge_count;
    if (target_edge_count == 0u || target_edge_count == target_pixels) {
        return solver_abstain(CAPTCHA_SOLVER_REASON_DEGENERATE_TARGET_EDGE);
    }

    candidate_index = 0u;
    for (y = 0u; y < target_height; ++y) {
        for (x = 0u; x < target_width; ++x) {
            if (g_target_edges[y * target_width + x] == 255u) {
                g_magnitude_or_positions.target_positions[candidate_index++] = (y << 16u) | x;
            }
        }
    }
    if (candidate_index != target_edge_count) {
        return solver_fail(CAPTCHA_SOLVER_ERR_INTERNAL, CAPTCHA_SOLVER_REASON_INTERNAL);
    }

    positions_width = background_width - target_width + 1u;
    positions_height = background_height - target_height + 1u;
    candidate_count = positions_width * positions_height;
    ncc_work = (uint64_t)candidate_count * (uint64_t)target_edge_count;
    g_result.candidate_count = candidate_count;
    if (ncc_work > g_config.max_ncc_work ||
        ncc_work > CAPTCHA_SOLVER_COMPILED_MAX_NCC_WORK) {
        return solver_fail(CAPTCHA_SOLVER_ERR_WORK_LIMIT, CAPTCHA_SOLVER_REASON_WORK_LIMIT);
    }
    g_result.ncc_work = (uint32_t)ncc_work;

    solver_build_integral(g_background_edges, background_width, background_height);
    candidate_index = 0u;
    for (y = 0u; y < positions_height; ++y) {
        for (x = 0u; x < positions_width; ++x) {
            double score = solver_ncc_score(
                target_width,
                target_height,
                background_width,
                x,
                y,
                target_edge_count
            );
            float stored_score = (float)score;
            g_queue_or_scores.scores[candidate_index] = stored_score;
            score_sum += (double)stored_score;
            score_square_sum += (double)stored_score * (double)stored_score;
            if ((double)stored_score > best_score) {
                best_score = (double)stored_score;
                best_index = candidate_index;
            }
            ++candidate_index;
        }
    }
    if (candidate_index != candidate_count || best_score < -1.0) {
        return solver_fail(CAPTCHA_SOLVER_ERR_INTERNAL, CAPTCHA_SOLVER_REASON_INTERNAL);
    }

    best_x = best_index % positions_width;
    best_y = best_index / positions_width;
    exclusion_x = solver_round_ratio_even(
        target_width * g_config.peak_exclusion_radius_permille, 1000u
    );
    exclusion_y = solver_round_ratio_even(
        target_height * g_config.peak_exclusion_radius_permille, 1000u
    );
    if (exclusion_x < 1u) {
        exclusion_x = 1u;
    }
    if (exclusion_y < 1u) {
        exclusion_y = 1u;
    }
    for (candidate_index = 0u; candidate_index < candidate_count; ++candidate_index) {
        uint32_t candidate_x = candidate_index % positions_width;
        uint32_t candidate_y = candidate_index / positions_width;
        uint32_t distance_x = candidate_x > best_x ? candidate_x - best_x : best_x - candidate_x;
        uint32_t distance_y = candidate_y > best_y ? candidate_y - best_y : best_y - candidate_y;
        double score = (double)g_queue_or_scores.scores[candidate_index];
        if ((distance_x > exclusion_x || distance_y > exclusion_y) && score > second_score) {
            second_score = score;
        }
    }

    peak_gap = best_score - second_score;
    if (peak_gap < 0.0) {
        peak_gap = 0.0;
    }
    score_mean = score_sum / (double)candidate_count;
    score_variance = score_square_sum / (double)candidate_count - score_mean * score_mean;
    if (score_variance < 0.0) {
        score_variance = 0.0;
    }
    peak_significance = score_variance > 1e-12
                            ? (best_score - score_mean) / solver_sqrt(score_variance)
                            : 0.0;
    if (peak_significance < 0.0) {
        peak_significance = 0.0;
    }

    matched_evidence = solver_evidence_region(
        g_background_gray,
        background_width,
        best_x,
        best_y,
        target_width,
        target_height
    );
    target_sharpness = target_evidence.sharpness_q20;
    g_result.local_sharpness_q20 = target_sharpness < matched_evidence.sharpness_q20
                                       ? target_sharpness
                                       : matched_evidence.sharpness_q20;
    g_result.target_left = best_x;
    g_result.target_top = best_y;
    g_result.target_center_x = best_x + target_width / 2u;
    g_result.target_center_y = best_y + target_height / 2u;
    g_result.confidence_q30 = solver_score_q30(best_score);
    g_result.top1_q30 = solver_score_q30(best_score);
    g_result.top2_q30 = solver_score_q30(second_score);
    g_result.peak_gap_q30 = solver_gap_q30(peak_gap);
    g_result.peak_significance_q20 = solver_q20(peak_significance, 4095.0);

    if (g_result.confidence_q30 < g_config.min_confidence_q30) {
        return solver_abstain(CAPTCHA_SOLVER_REASON_LOW_CONFIDENCE);
    }
    if (g_result.peak_gap_q30 < g_config.min_peak_gap_q30) {
        return solver_abstain(CAPTCHA_SOLVER_REASON_AMBIGUOUS_PEAK);
    }
    if (g_result.peak_significance_q20 < g_config.min_peak_significance_q20) {
        return solver_abstain(CAPTCHA_SOLVER_REASON_LOW_PEAK_SIGNIFICANCE);
    }
    if (g_result.local_sharpness_q20 < g_config.min_local_sharpness_q20) {
        return solver_abstain(CAPTCHA_SOLVER_REASON_LOW_LOCAL_SHARPNESS);
    }

    g_result.decision = CAPTCHA_SOLVER_DECISION_MATCH;
    g_result.reason = CAPTCHA_SOLVER_REASON_NONE;
    return CAPTCHA_SOLVER_COMPLETED;
}
