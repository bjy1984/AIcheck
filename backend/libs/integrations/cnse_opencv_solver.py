"""OpenCV matcher for the CNSE API image pair.

This is the Python counterpart of ``extension/solver/opencv-solver.js``.  It
keeps the same strategy ordering: alpha-gap, masked photometric, then edge
template matching.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Any

ALGORITHM = "opencv-edge-template-v1"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_EDGE = 4_096
MAX_IMAGE_PIXELS = 20_000_000
ALPHA_SUPPORT_THRESHOLD = 8
ALPHA_CROP_MARGIN = 2
PHOTOMETRIC_ALPHA_THRESHOLD = 224
MAX_TEMPLATE_PIXELS = 250_000
MAX_CANDIDATES = 200_000
MAX_OPERATIONS = 30_000_000
MATCH_ORIGIN_TOLERANCE = 3


class CnseOpenCvError(RuntimeError):
    """Raised when an image pair cannot produce a trustworthy match."""


@dataclass(frozen=True)
class OpenCvMatch:
    confidence: float
    left: int
    top: int
    width: int
    height: int
    background_width: int
    background_height: int
    strategy: str

    @property
    def target_x(self) -> int:
        return self.left + self.width // 2

    @property
    def target_y(self) -> int:
        return self.top + self.height // 2


@dataclass(frozen=True)
class _Candidate:
    confidence: float
    left: int
    top: int
    strategy: str
    ambiguous: bool = False


def _load_rgba(data: bytes, label: str) -> Any:
    if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
        raise CnseOpenCvError(f"{label} image has an invalid byte length")
    try:
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = (image.format or "").upper()
            if (
                image_format not in {"PNG", "JPEG", "WEBP"}
                or width <= 0
                or height <= 0
                or width > MAX_IMAGE_EDGE
                or height > MAX_IMAGE_EDGE
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise CnseOpenCvError(f"{label} image dimensions or format are invalid")
            image.load()
            return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    except CnseOpenCvError:
        raise
    except Exception as exc:
        raise CnseOpenCvError(f"{label} image cannot be decoded") from exc


def _alpha_bounds(image: Any) -> tuple[int, int, int, int] | None:
    import numpy as np

    alpha = image[:, :, 3]
    supported_y, supported_x = np.nonzero(alpha > ALPHA_SUPPORT_THRESHOLD)
    transparent = int(np.count_nonzero(alpha <= ALPHA_SUPPORT_THRESHOLD))
    if (
        transparent == 0
        or supported_x.size < 4
        or int(supported_x.max()) - int(supported_x.min()) < 2
        or int(supported_y.max()) - int(supported_y.min()) < 2
    ):
        return None
    left = max(0, int(supported_x.min()) - ALPHA_CROP_MARGIN)
    top = max(0, int(supported_y.min()) - ALPHA_CROP_MARGIN)
    right = min(image.shape[1] - 1, int(supported_x.max()) + ALPHA_CROP_MARGIN)
    bottom = min(image.shape[0] - 1, int(supported_y.max()) + ALPHA_CROP_MARGIN)
    return left, top, right - left + 1, bottom - top + 1


def _correlate_samples(
    background_values: Any,
    sample_x: Any,
    sample_y: Any,
    template_values: Any,
    *,
    output_width: int,
    output_height: int,
) -> Any:
    import numpy as np

    count = int(template_values.size)
    template = template_values.astype(np.float64, copy=False)
    template_sum = float(template.sum())
    template_square_sum = float(np.square(template).sum())
    template_variance = count * template_square_sum - template_sum * template_sum
    background_sum = np.zeros((output_height, output_width), dtype=np.float64)
    background_square_sum = np.zeros_like(background_sum)
    product_sum = np.zeros_like(background_sum)
    for x, y, value in zip(sample_x, sample_y, template):
        view = background_values[
            int(y) : int(y) + output_height,
            int(x) : int(x) + output_width,
        ].astype(np.float64, copy=False)
        background_sum += view
        background_square_sum += view * view
        product_sum += view * value
    background_variance = count * background_square_sum - background_sum * background_sum
    denominator = np.sqrt(np.maximum(0.0, template_variance * background_variance))
    numerator = count * product_sum - template_sum * background_sum
    scores = np.full_like(numerator, np.nan)
    np.divide(numerator, denominator, out=scores, where=denominator > 0)
    return np.clip(scores, -1.0, 1.0)


def _best_unique(
    scores: Any,
    *,
    exclusion_width: int,
    exclusion_height: int,
    min_correlation: float,
    min_uniqueness: float,
    strategy: str,
) -> _Candidate | None:
    import numpy as np

    finite = np.isfinite(scores)
    if not bool(finite.any()):
        return None
    safe = np.where(finite, scores, -np.inf)
    flat_index = int(np.argmax(safe))
    top, left = (int(value) for value in np.unravel_index(flat_index, safe.shape))
    confidence = float(safe[top, left])
    if confidence < min_correlation:
        return None
    runner = safe.copy()
    runner[
        max(0, top - exclusion_height) : min(safe.shape[0], top + exclusion_height + 1),
        max(0, left - exclusion_width) : min(safe.shape[1], left + exclusion_width + 1),
    ] = -np.inf
    runner_up = float(np.max(runner))
    uniqueness = 1.0 if not math.isfinite(runner_up) or runner_up < -0.5 else confidence - runner_up
    return _Candidate(
        confidence=confidence,
        left=left,
        top=top,
        strategy=strategy,
        ambiguous=uniqueness < min_uniqueness,
    )


def _masked_alpha_gap(background: Any, puzzle: Any) -> _Candidate | None:
    import numpy as np

    bounds = _alpha_bounds(puzzle)
    if bounds is None or bounds[2] * bounds[3] > MAX_TEMPLATE_PIXELS:
        return None
    background_alpha = background[:, :, 3]
    if (
        int(background_alpha.max()) - int(background_alpha.min()) < 8
        or int(np.count_nonzero(background_alpha >= 250)) < background.shape[0] * background.shape[1] / 2
    ):
        return None
    output_width = background.shape[1] - puzzle.shape[1] + 1
    output_height = background.shape[0] - puzzle.shape[0] + 1
    candidates = output_width * output_height
    if candidates < 1 or candidates > MAX_CANDIDATES:
        return None
    left, top, width, height = bounds
    point_x = np.tile(np.arange(left, left + width), height)
    point_y = np.repeat(np.arange(top, top + height), width)
    stride = max(1, math.ceil(point_x.size * candidates / MAX_OPERATIONS))
    point_x = point_x[::stride]
    point_y = point_y[::stride]
    template = puzzle[point_y, point_x, 3].astype(np.float64)
    if template.size < 64 or float(template.std()) < 12:
        return None
    scores = _correlate_samples(
        255 - background_alpha,
        point_x,
        point_y,
        template,
        output_width=output_width,
        output_height=output_height,
    )
    return _best_unique(
        scores,
        exclusion_width=max(4, width // 3),
        exclusion_height=max(4, height // 3),
        min_correlation=0.9,
        min_uniqueness=0.1,
        strategy="masked-alpha-gap",
    )


def _luminance(image: Any) -> Any:
    rgb = image[:, :, :3].astype("float64")
    return (77 * rgb[:, :, 0] + 150 * rgb[:, :, 1] + 29 * rgb[:, :, 2]) / 256


def _masked_photometric(background: Any, puzzle: Any) -> _Candidate | None:
    import numpy as np

    bounds = _alpha_bounds(puzzle)
    if bounds is None or puzzle.shape[0] * puzzle.shape[1] > MAX_TEMPLATE_PIXELS:
        return None
    alpha = puzzle[:, :, 3]
    opaque = alpha >= PHOTOMETRIC_ALPHA_THRESHOLD
    interior = np.zeros_like(opaque)
    interior[1:-1, 1:-1] = (
        opaque[1:-1, 1:-1]
        & opaque[1:-1, :-2]
        & opaque[1:-1, 2:]
        & opaque[:-2, 1:-1]
        & opaque[2:, 1:-1]
    )
    point_y, point_x = np.nonzero(interior)
    if point_x.size < 64:
        return None
    output_width = background.shape[1] - puzzle.shape[1] + 1
    output_height = background.shape[0] - puzzle.shape[0] + 1
    candidates = output_width * output_height
    if candidates < 1 or candidates > MAX_CANDIDATES:
        return None
    puzzle_luminance = _luminance(puzzle)
    stride = max(1, math.ceil(point_x.size * candidates / MAX_OPERATIONS))
    point_x = point_x[::stride]
    point_y = point_y[::stride]
    template = puzzle_luminance[point_y, point_x]
    if template.size < 64 or float(template.std()) < 6:
        return None
    scores = _correlate_samples(
        _luminance(background),
        point_x,
        point_y,
        template,
        output_width=output_width,
        output_height=output_height,
    )
    candidate = _best_unique(
        scores,
        exclusion_width=max(4, bounds[2] // 3),
        exclusion_height=max(4, bounds[3] // 3),
        min_correlation=0.72,
        min_uniqueness=0.0,
        strategy="masked-photometric",
    )
    if candidate is None:
        return None
    required = 0.04 if candidate.confidence >= 0.95 else 0.08
    # Re-evaluate with the extension's confidence-dependent uniqueness threshold.
    return _best_unique(
        scores,
        exclusion_width=max(4, bounds[2] // 3),
        exclusion_height=max(4, bounds[3] // 3),
        min_correlation=0.72,
        min_uniqueness=required,
        strategy="masked-photometric",
    )


def _edge_match(background: Any, puzzle: Any) -> _Candidate | None:
    import cv2
    import numpy as np

    background_gray = cv2.cvtColor(background, cv2.COLOR_RGBA2GRAY)
    background_edges = cv2.Canny(background_gray, 50, 150, apertureSize=3, L2gradient=False)
    if not bool(np.any(background_edges)):
        return None
    variants = [("rgba-full", puzzle, 0, 0)]
    bounds = _alpha_bounds(puzzle)
    if bounds is not None:
        alpha = puzzle[:, :, 3]
        full = np.empty_like(puzzle)
        full[:, :, :3] = alpha[:, :, None]
        full[:, :, 3] = 255
        variants.append(("alpha-mask-full", full, 0, 0))
        left, top, width, height = bounds
        if (left, top, width, height) != (0, 0, puzzle.shape[1], puzzle.shape[0]):
            crop_alpha = alpha[top : top + height, left : left + width]
            crop = np.empty((height, width, 4), dtype=np.uint8)
            crop[:, :, :3] = crop_alpha[:, :, None]
            crop[:, :, 3] = 255
            variants.append(("alpha-mask-crop", crop, left, top))
    best = None
    for strategy, variant, offset_x, offset_y in variants:
        edges = cv2.Canny(
            cv2.cvtColor(variant, cv2.COLOR_RGBA2GRAY),
            50,
            150,
            apertureSize=3,
            L2gradient=False,
        )
        if not bool(np.any(edges)):
            continue
        correlation = cv2.matchTemplate(background_edges, edges, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, location = cv2.minMaxLoc(correlation)
        raw_left = int(location[0]) - offset_x
        raw_top = int(location[1]) - offset_y
        maximum_x = background.shape[1] - puzzle.shape[1]
        maximum_y = background.shape[0] - puzzle.shape[0]
        if (
            raw_left < -MATCH_ORIGIN_TOLERANCE
            or raw_top < -MATCH_ORIGIN_TOLERANCE
            or raw_left > maximum_x + MATCH_ORIGIN_TOLERANCE
            or raw_top > maximum_y + MATCH_ORIGIN_TOLERANCE
        ):
            continue
        candidate = _Candidate(
            confidence=max(-1.0, min(1.0, float(confidence))),
            left=max(0, min(maximum_x, raw_left)),
            top=max(0, min(maximum_y, raw_top)),
            strategy=strategy,
        )
        if best is None or candidate.confidence > best.confidence:
            best = candidate
    return best


def solve_opencv_from_bytes(
    puzzle_bytes: bytes,
    background_bytes: bytes,
    *,
    min_confidence: float = 0.50,
) -> OpenCvMatch:
    if (
        isinstance(min_confidence, bool)
        or not isinstance(min_confidence, (int, float))
        or not math.isfinite(min_confidence)
        or not 0 <= float(min_confidence) <= 1
    ):
        raise CnseOpenCvError("minimum confidence must be between 0 and 1")
    background = _load_rgba(background_bytes, "background")
    puzzle = _load_rgba(puzzle_bytes, "puzzle")
    if puzzle.shape[1] > background.shape[1] or puzzle.shape[0] > background.shape[0]:
        raise CnseOpenCvError("puzzle image is larger than background image")

    alpha_gap = _masked_alpha_gap(background, puzzle)
    photometric = _masked_photometric(background, puzzle)
    edge = _edge_match(background, puzzle)
    if alpha_gap is not None and alpha_gap.ambiguous and not (photometric and not photometric.ambiguous):
        raise CnseOpenCvError("multiple image regions contain the same puzzle silhouette")
    if photometric is not None and photometric.ambiguous and not (alpha_gap and not alpha_gap.ambiguous):
        raise CnseOpenCvError("multiple image regions match the puzzle texture equally well")
    candidate = next(
        (value for value in (alpha_gap, photometric, edge) if value is not None and not value.ambiguous),
        None,
    )
    if candidate is None:
        raise CnseOpenCvError("OpenCV returned no usable template match")
    if candidate.confidence < float(min_confidence):
        raise CnseOpenCvError(
            f"match confidence {candidate.confidence:.3f} is below the required {float(min_confidence):.3f}"
        )
    return OpenCvMatch(
        confidence=candidate.confidence,
        left=candidate.left,
        top=candidate.top,
        width=puzzle.shape[1],
        height=puzzle.shape[0],
        background_width=background.shape[1],
        background_height=background.shape[0],
        strategy=candidate.strategy,
    )
