export const OPENCV_ALGORITHM = "opencv-edge-template-v1";
export const DEFAULT_MIN_CONFIDENCE = 0.5;
export const MAX_IMAGE_PIXELS = 20_000_000;
export const MAX_IMAGE_EDGE = 4_096;

const CANNY_LOW_THRESHOLD = 50;
const CANNY_HIGH_THRESHOLD = 150;
const CANNY_APERTURE_SIZE = 3;
const ALPHA_SUPPORT_THRESHOLD = 8;
const ALPHA_CROP_MARGIN = 2;
const PHOTOMETRIC_ALPHA_THRESHOLD = 224;
const PHOTOMETRIC_MIN_POINTS = 64;
const PHOTOMETRIC_MIN_STDDEV = 6;
const PHOTOMETRIC_MIN_CORRELATION = 0.72;
const PHOTOMETRIC_MIN_UNIQUENESS = 0.08;
const PHOTOMETRIC_STRONG_UNIQUENESS = 0.04;
const PHOTOMETRIC_STRONG_CORRELATION = 0.95;
const PHOTOMETRIC_MAX_TEMPLATE_PIXELS = 250_000;
const PHOTOMETRIC_MAX_CANDIDATES = 200_000;
const PHOTOMETRIC_MAX_OPERATIONS = 30_000_000;
const ALPHA_GAP_MIN_POINTS = 64;
const ALPHA_GAP_MIN_STDDEV = 12;
const ALPHA_GAP_MIN_BACKGROUND_RANGE = 8;
const ALPHA_GAP_MIN_CORRELATION = 0.9;
const ALPHA_GAP_MIN_UNIQUENESS = 0.1;
const ALPHA_GAP_MAX_TEMPLATE_PIXELS = 250_000;
const ALPHA_GAP_MAX_CANDIDATES = 200_000;
const ALPHA_GAP_MAX_OPERATIONS = 30_000_000;
const MATCH_ORIGIN_TOLERANCE = 3;
const RUNTIME_TIMEOUT_MS = 30_000;
const runtimeWaits = new WeakMap();

export class OpenCvSolverError extends Error {
  constructor(code, message, options = undefined) {
    super(message, options);
    this.name = "OpenCvSolverError";
    this.code = code;
  }
}

function fail(code, message, options = undefined) {
  throw new OpenCvSolverError(code, message, options);
}

function isPositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function byteView(value) {
  if (!ArrayBuffer.isView(value) || value.BYTES_PER_ELEMENT !== 1) return null;
  return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
}

export function validateRgbaImage(image, label = "image") {
  if (!image || typeof image !== "object" || Array.isArray(image)) {
    fail("IMAGE_INVALID", `${label} must be an RGBA image descriptor`);
  }
  const { width, height } = image;
  if (!isPositiveInteger(width) || !isPositiveInteger(height)) {
    fail("IMAGE_INVALID", `${label} dimensions must be positive integers`);
  }
  if (width > MAX_IMAGE_EDGE || height > MAX_IMAGE_EDGE || width * height > MAX_IMAGE_PIXELS) {
    fail("IMAGE_LIMIT_EXCEEDED", `${label} dimensions exceed the local processing limit`);
  }
  const data = byteView(image.data);
  if (!data || data.byteLength !== width * height * 4) {
    fail("IMAGE_INVALID", `${label} must contain exactly width * height * 4 RGBA bytes`);
  }
  return Object.freeze({ width, height, data });
}

function validateMinConfidence(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    fail("SOLVER_CONFIG_INVALID", "minimum confidence must be a finite number from 0 to 1");
  }
  return value;
}

function runtimeReady(cv) {
  return Boolean(
    cv &&
    (typeof cv === "object" || typeof cv === "function") &&
    typeof cv.Mat === "function" &&
    typeof cv.cvtColor === "function" &&
    typeof cv.Canny === "function" &&
    typeof cv.matchTemplate === "function" &&
    typeof cv.minMaxLoc === "function" &&
    Number.isInteger(cv.CV_8UC4) &&
    Number.isInteger(cv.COLOR_RGBA2GRAY) &&
    Number.isInteger(cv.TM_CCOEFF_NORMED),
  );
}

export function assertOpenCvRuntime(cv) {
  if (!runtimeReady(cv)) {
    const missing = [];
    for (const name of ["Mat", "cvtColor", "Canny", "matchTemplate", "minMaxLoc"]) {
      if (typeof cv?.[name] !== "function") missing.push(name);
    }
    for (const name of ["CV_8UC4", "COLOR_RGBA2GRAY", "TM_CCOEFF_NORMED"]) {
      if (!Number.isInteger(cv?.[name])) missing.push(name);
    }
    fail(
      "OPENCV_UNAVAILABLE",
      `the bundled OpenCV runtime is not ready${missing.length ? ` (missing ${missing.join(",")})` : ""}`,
    );
  }
  return cv;
}

// The official OpenCV.js build exposes a thenable Module rather than a native
// Promise. Resolve only readiness here: resolving a Promise with the Module
// itself would recursively assimilate its persistent `then` method.
export function waitForOpenCvRuntime(cv = globalThis.cv, { timeoutMs = RUNTIME_TIMEOUT_MS } = {}) {
  if (!cv || (typeof cv !== "object" && typeof cv !== "function")) {
    return Promise.reject(new OpenCvSolverError(
      "OPENCV_UNAVAILABLE",
      "the bundled OpenCV runtime was not loaded",
    ));
  }
  if (runtimeReady(cv)) return Promise.resolve(Object.freeze({ runtime: cv }));
  if (runtimeWaits.has(cv)) return runtimeWaits.get(cv);
  if (typeof cv.then !== "function") {
    return Promise.reject(new OpenCvSolverError(
      "OPENCV_UNAVAILABLE",
      "the bundled OpenCV runtime cannot be initialized",
    ));
  }
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) {
    return Promise.reject(new OpenCvSolverError(
      "SOLVER_CONFIG_INVALID",
      "OpenCV runtime timeout must be a positive integer",
    ));
  }

  const pending = new Promise((resolve, reject) => {
    let finished = false;
    let candidate = cv;
    let lastError = null;
    const timer = setTimeout(() => {
      if (finished) return;
      finished = true;
      reject(new OpenCvSolverError(
        "OPENCV_UNAVAILABLE",
        lastError?.message || "the bundled OpenCV runtime did not initialize in time",
      ));
    }, timeoutMs);

    const check = () => {
      if (finished) return;
      for (const runtime of candidate === cv ? [candidate] : [candidate, cv]) {
        try {
          assertOpenCvRuntime(runtime);
          finished = true;
          clearTimeout(timer);
          resolve(Object.freeze({ runtime }));
          return;
        } catch (error) {
          lastError = error;
        }
      }
      setTimeout(check, 25);
    };

    try {
      cv.then((resolved) => {
        if (resolved && (typeof resolved === "object" || typeof resolved === "function")) {
          candidate = resolved;
        }
        check();
      });
      check();
    } catch (error) {
      finished = true;
      clearTimeout(timer);
      reject(new OpenCvSolverError(
        "OPENCV_UNAVAILABLE",
        "the bundled OpenCV runtime failed to initialize",
        { cause: error },
      ));
    }
  });
  runtimeWaits.set(cv, pending);
  return pending;
}

function matFromRgba(cv, image) {
  const mat = new cv.Mat(image.height, image.width, cv.CV_8UC4);
  mat.data.set(image.data);
  return mat;
}

function alphaSupportBounds(image) {
  let left = image.width;
  let top = image.height;
  let right = -1;
  let bottom = -1;
  let supportPixels = 0;
  let transparentPixels = 0;
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      const alpha = image.data[(y * image.width + x) * 4 + 3];
      if (alpha <= ALPHA_SUPPORT_THRESHOLD) {
        transparentPixels += 1;
        continue;
      }
      supportPixels += 1;
      left = Math.min(left, x);
      top = Math.min(top, y);
      right = Math.max(right, x);
      bottom = Math.max(bottom, y);
    }
  }
  if (transparentPixels === 0 || supportPixels < 4 || right - left < 2 || bottom - top < 2) {
    return null;
  }
  left = Math.max(0, left - ALPHA_CROP_MARGIN);
  top = Math.max(0, top - ALPHA_CROP_MARGIN);
  right = Math.min(image.width - 1, right + ALPHA_CROP_MARGIN);
  bottom = Math.min(image.height - 1, bottom + ALPHA_CROP_MARGIN);
  return Object.freeze({
    x: left,
    y: top,
    width: right - left + 1,
    height: bottom - top + 1,
  });
}

function alphaMaskImage(image, bounds) {
  const data = new Uint8ClampedArray(bounds.width * bounds.height * 4);
  for (let y = 0; y < bounds.height; y += 1) {
    for (let x = 0; x < bounds.width; x += 1) {
      const sourceOffset = ((bounds.y + y) * image.width + bounds.x + x) * 4;
      const destinationOffset = (y * bounds.width + x) * 4;
      const alpha = image.data[sourceOffset + 3];
      data[destinationOffset] = alpha;
      data[destinationOffset + 1] = alpha;
      data[destinationOffset + 2] = alpha;
      data[destinationOffset + 3] = 255;
    }
  }
  return Object.freeze({ width: bounds.width, height: bounds.height, data });
}

function buildMatchVariants(puzzle) {
  const variants = [{
    name: "rgba-full",
    image: puzzle,
    offsetX: 0,
    offsetY: 0,
  }];
  const bounds = alphaSupportBounds(puzzle);
  if (!bounds) return variants;

  const fullBounds = { x: 0, y: 0, width: puzzle.width, height: puzzle.height };
  variants.push({
    name: "alpha-mask-full",
    image: alphaMaskImage(puzzle, fullBounds),
    offsetX: 0,
    offsetY: 0,
  });
  if (bounds.x !== 0 || bounds.y !== 0 ||
      bounds.width !== puzzle.width || bounds.height !== puzzle.height) {
    variants.push({
      name: "alpha-mask-crop",
      image: alphaMaskImage(puzzle, bounds),
      offsetX: bounds.x,
      offsetY: bounds.y,
    });
  }
  return variants;
}

function luminance(data, offset) {
  return (77 * data[offset] + 150 * data[offset + 1] + 29 * data[offset + 2]) / 256;
}

// Some slider providers encode the highlighted target directly in the PNG
// alpha channel: the movable piece is mostly transparent, while the matching
// background region has a weaker copy of the same alpha silhouette. Matching
// those two signals is independent of scene texture, which makes it reliable
// on flat sky, snow, walls, and other low-contrast photographs.
function maskedAlphaGapMatch(background, puzzle) {
  const bounds = alphaSupportBounds(puzzle);
  if (!bounds || bounds.width * bounds.height > ALPHA_GAP_MAX_TEMPLATE_PIXELS) return null;

  let minimumBackgroundAlpha = 255;
  let maximumBackgroundAlpha = 0;
  let opaqueBackgroundPixels = 0;
  for (let offset = 3; offset < background.data.length; offset += 4) {
    const alpha = background.data[offset];
    minimumBackgroundAlpha = Math.min(minimumBackgroundAlpha, alpha);
    maximumBackgroundAlpha = Math.max(maximumBackgroundAlpha, alpha);
    if (alpha >= 250) opaqueBackgroundPixels += 1;
  }
  if (maximumBackgroundAlpha - minimumBackgroundAlpha < ALPHA_GAP_MIN_BACKGROUND_RANGE ||
      opaqueBackgroundPixels < background.width * background.height / 2) return null;

  const maximumX = background.width - puzzle.width;
  const maximumY = background.height - puzzle.height;
  const rowCandidates = maximumX + 1;
  const candidateCount = rowCandidates * (maximumY + 1);
  if (candidateCount < 1 || candidateCount > ALPHA_GAP_MAX_CANDIDATES) return null;

  const pointCount = bounds.width * bounds.height;
  const stride = Math.max(
    1,
    Math.ceil(pointCount * candidateCount / ALPHA_GAP_MAX_OPERATIONS),
  );
  const samples = [];
  for (let point = 0; point < pointCount; point += stride) {
    const x = bounds.x + point % bounds.width;
    const y = bounds.y + Math.floor(point / bounds.width);
    const alpha = puzzle.data[(y * puzzle.width + x) * 4 + 3];
    samples.push(x, y, alpha);
  }
  const selectedCount = samples.length / 3;
  if (selectedCount < ALPHA_GAP_MIN_POINTS) return null;

  let templateSum = 0;
  let templateSquareSum = 0;
  for (let index = 2; index < samples.length; index += 3) {
    const value = samples[index];
    templateSum += value;
    templateSquareSum += value * value;
  }
  const templateVariance = selectedCount * templateSquareSum - templateSum * templateSum;
  const templateStddev = Math.sqrt(Math.max(0, templateVariance)) / selectedCount;
  if (!Number.isFinite(templateStddev) || templateStddev < ALPHA_GAP_MIN_STDDEV) return null;

  const scores = new Float32Array(candidateCount);
  scores.fill(Number.NaN);
  let bestScore = -1;
  let bestX = -1;
  let bestY = -1;
  for (let originY = 0; originY <= maximumY; originY += 1) {
    for (let originX = 0; originX <= maximumX; originX += 1) {
      let backgroundSum = 0;
      let backgroundSquareSum = 0;
      let productSum = 0;
      for (let index = 0; index < samples.length; index += 3) {
        const x = samples[index];
        const y = samples[index + 1];
        const templateValue = samples[index + 2];
        const backgroundOffset = ((originY + y) * background.width + originX + x) * 4;
        const backgroundValue = 255 - background.data[backgroundOffset + 3];
        backgroundSum += backgroundValue;
        backgroundSquareSum += backgroundValue * backgroundValue;
        productSum += templateValue * backgroundValue;
      }
      const backgroundVariance = selectedCount * backgroundSquareSum -
        backgroundSum * backgroundSum;
      const denominator = Math.sqrt(Math.max(0, templateVariance * backgroundVariance));
      if (!Number.isFinite(denominator) || denominator === 0) continue;
      const numerator = selectedCount * productSum - templateSum * backgroundSum;
      const score = Math.max(-1, Math.min(1, numerator / denominator));
      const candidateIndex = originY * rowCandidates + originX;
      scores[candidateIndex] = score;
      if (score > bestScore) {
        bestScore = score;
        bestX = originX;
        bestY = originY;
      }
    }
  }
  if (bestX < 0 || bestScore < ALPHA_GAP_MIN_CORRELATION) return null;

  const exclusionX = Math.max(4, Math.floor(bounds.width / 3));
  const exclusionY = Math.max(4, Math.floor(bounds.height / 3));
  let runnerUp = -1;
  for (let originY = 0; originY <= maximumY; originY += 1) {
    for (let originX = 0; originX <= maximumX; originX += 1) {
      if (Math.abs(originX - bestX) <= exclusionX &&
          Math.abs(originY - bestY) <= exclusionY) continue;
      const score = scores[originY * rowCandidates + originX];
      if (Number.isFinite(score) && score > runnerUp) runnerUp = score;
    }
  }
  const uniqueness = runnerUp < -0.5 ? 1 : bestScore - runnerUp;
  if (uniqueness < ALPHA_GAP_MIN_UNIQUENESS) {
    return Object.freeze({ ambiguous: true, confidence: bestScore, left: bestX, top: bestY });
  }
  return Object.freeze({
    ambiguous: false,
    confidence: bestScore,
    left: bestX,
    top: bestY,
    strategy: "masked-alpha-gap",
  });
}

function opaqueInteriorSamples(puzzle) {
  if (puzzle.width * puzzle.height > PHOTOMETRIC_MAX_TEMPLATE_PIXELS ||
      puzzle.width < 3 || puzzle.height < 3) return null;
  const samples = [];
  const alphaAt = (x, y) => puzzle.data[(y * puzzle.width + x) * 4 + 3];
  for (let y = 1; y < puzzle.height - 1; y += 1) {
    for (let x = 1; x < puzzle.width - 1; x += 1) {
      if (
        alphaAt(x, y) < PHOTOMETRIC_ALPHA_THRESHOLD ||
        alphaAt(x - 1, y) < PHOTOMETRIC_ALPHA_THRESHOLD ||
        alphaAt(x + 1, y) < PHOTOMETRIC_ALPHA_THRESHOLD ||
        alphaAt(x, y - 1) < PHOTOMETRIC_ALPHA_THRESHOLD ||
        alphaAt(x, y + 1) < PHOTOMETRIC_ALPHA_THRESHOLD
      ) continue;
      const offset = (y * puzzle.width + x) * 4;
      samples.push(x, y, luminance(puzzle.data, offset));
    }
  }
  return samples.length / 3 >= PHOTOMETRIC_MIN_POINTS ? samples : null;
}

function maskedPhotometricMatch(background, puzzle) {
  const bounds = alphaSupportBounds(puzzle);
  const samples = bounds ? opaqueInteriorSamples(puzzle) : null;
  if (!samples) return null;
  const maximumX = background.width - puzzle.width;
  const maximumY = background.height - puzzle.height;
  const rowCandidates = maximumX + 1;
  const candidateCount = rowCandidates * (maximumY + 1);
  if (candidateCount < 1 || candidateCount > PHOTOMETRIC_MAX_CANDIDATES) return null;

  const pointCount = samples.length / 3;
  const stride = Math.max(
    1,
    Math.ceil(pointCount * candidateCount / PHOTOMETRIC_MAX_OPERATIONS),
  );
  const selected = [];
  for (let point = 0; point < pointCount; point += stride) {
    const offset = point * 3;
    selected.push(samples[offset], samples[offset + 1], samples[offset + 2]);
  }
  const selectedCount = selected.length / 3;
  if (selectedCount < PHOTOMETRIC_MIN_POINTS) return null;

  let templateSum = 0;
  let templateSquareSum = 0;
  for (let index = 2; index < selected.length; index += 3) {
    const value = selected[index];
    templateSum += value;
    templateSquareSum += value * value;
  }
  const templateVariance = selectedCount * templateSquareSum - templateSum * templateSum;
  const templateStddev = Math.sqrt(Math.max(0, templateVariance)) / selectedCount;
  if (!Number.isFinite(templateStddev) || templateStddev < PHOTOMETRIC_MIN_STDDEV) return null;

  const scores = new Float32Array(candidateCount);
  scores.fill(Number.NaN);
  let bestScore = -1;
  let bestX = -1;
  let bestY = -1;
  for (let originY = 0; originY <= maximumY; originY += 1) {
    for (let originX = 0; originX <= maximumX; originX += 1) {
      let backgroundSum = 0;
      let backgroundSquareSum = 0;
      let productSum = 0;
      for (let index = 0; index < selected.length; index += 3) {
        const x = selected[index];
        const y = selected[index + 1];
        const templateValue = selected[index + 2];
        const backgroundOffset = ((originY + y) * background.width + originX + x) * 4;
        const backgroundValue = luminance(background.data, backgroundOffset);
        backgroundSum += backgroundValue;
        backgroundSquareSum += backgroundValue * backgroundValue;
        productSum += templateValue * backgroundValue;
      }
      const backgroundVariance = selectedCount * backgroundSquareSum -
        backgroundSum * backgroundSum;
      const denominator = Math.sqrt(Math.max(0, templateVariance * backgroundVariance));
      if (!Number.isFinite(denominator) || denominator === 0) continue;
      const numerator = selectedCount * productSum - templateSum * backgroundSum;
      const score = Math.max(-1, Math.min(1, numerator / denominator));
      const candidateIndex = originY * rowCandidates + originX;
      scores[candidateIndex] = score;
      if (score > bestScore) {
        bestScore = score;
        bestX = originX;
        bestY = originY;
      }
    }
  }
  if (bestX < 0 || bestScore < PHOTOMETRIC_MIN_CORRELATION) return null;

  const exclusionX = Math.max(4, Math.floor(bounds.width / 3));
  const exclusionY = Math.max(4, Math.floor(bounds.height / 3));
  let runnerUp = -1;
  for (let originY = 0; originY <= maximumY; originY += 1) {
    for (let originX = 0; originX <= maximumX; originX += 1) {
      if (Math.abs(originX - bestX) <= exclusionX &&
          Math.abs(originY - bestY) <= exclusionY) continue;
      const score = scores[originY * rowCandidates + originX];
      if (Number.isFinite(score) && score > runnerUp) runnerUp = score;
    }
  }
  const uniqueness = runnerUp < -0.5 ? 1 : bestScore - runnerUp;
  const requiredUniqueness = bestScore >= PHOTOMETRIC_STRONG_CORRELATION
    ? PHOTOMETRIC_STRONG_UNIQUENESS
    : PHOTOMETRIC_MIN_UNIQUENESS;
  if (uniqueness < requiredUniqueness) {
    return Object.freeze({ ambiguous: true, confidence: bestScore, left: bestX, top: bestY });
  }
  return Object.freeze({
    ambiguous: false,
    confidence: bestScore,
    left: bestX,
    top: bestY,
    strategy: "masked-photometric",
  });
}

function clampedMatchOrigin(value, maximum) {
  if (!Number.isInteger(value) || value < -MATCH_ORIGIN_TOLERANCE ||
      value > maximum + MATCH_ORIGIN_TOLERANCE) return null;
  return Math.min(maximum, Math.max(0, value));
}

function hasEdgePixels(mat) {
  const data = mat?.data;
  if (!data || typeof data.length !== "number") return false;
  for (let index = 0; index < data.length; index += 1) {
    if (data[index] !== 0) return true;
  }
  return false;
}

function safeDelete(mat) {
  try {
    mat?.delete?.();
  } catch {
    // A failed delete must not hide the matching result or its real error.
  }
}

export function solvePuzzleImages(
  { background, puzzle, minConfidence = DEFAULT_MIN_CONFIDENCE },
  cv = globalThis.cv,
) {
  const runtime = assertOpenCvRuntime(cv);
  const backgroundImage = validateRgbaImage(background, "background");
  const puzzleImage = validateRgbaImage(puzzle, "puzzle");
  const requiredConfidence = validateMinConfidence(minConfidence);

  if (puzzleImage.width > backgroundImage.width || puzzleImage.height > backgroundImage.height) {
    fail("TEMPLATE_TOO_LARGE", "the puzzle image is larger than the background image");
  }

  const mats = [];
  try {
    const alphaGap = maskedAlphaGapMatch(backgroundImage, puzzleImage);
    const photometric = maskedPhotometricMatch(backgroundImage, puzzleImage);
    const backgroundRgba = matFromRgba(runtime, backgroundImage);
    const backgroundGray = new runtime.Mat();
    const backgroundEdges = new runtime.Mat();
    mats.push(backgroundRgba, backgroundGray, backgroundEdges);

    runtime.cvtColor(backgroundRgba, backgroundGray, runtime.COLOR_RGBA2GRAY, 0);
    runtime.Canny(
      backgroundGray,
      backgroundEdges,
      CANNY_LOW_THRESHOLD,
      CANNY_HIGH_THRESHOLD,
      CANNY_APERTURE_SIZE,
      false,
    );
    const backgroundHasEdges = hasEdgePixels(backgroundEdges);
    let edgeBest = null;
    let templateWithEdges = false;
    let invalidMatch = false;
    for (const variant of backgroundHasEdges ? buildMatchVariants(puzzleImage) : []) {
      if (variant.image.width > backgroundImage.width ||
          variant.image.height > backgroundImage.height) continue;
      const puzzleRgba = matFromRgba(runtime, variant.image);
      const puzzleGray = new runtime.Mat();
      const puzzleEdges = new runtime.Mat();
      const correlation = new runtime.Mat();
      mats.push(puzzleRgba, puzzleGray, puzzleEdges, correlation);
      runtime.cvtColor(puzzleRgba, puzzleGray, runtime.COLOR_RGBA2GRAY, 0);
      runtime.Canny(
        puzzleGray,
        puzzleEdges,
        CANNY_LOW_THRESHOLD,
        CANNY_HIGH_THRESHOLD,
        CANNY_APERTURE_SIZE,
        false,
      );
      if (!hasEdgePixels(puzzleEdges)) continue;
      templateWithEdges = true;

      runtime.matchTemplate(
        backgroundEdges,
        puzzleEdges,
        correlation,
        runtime.TM_CCOEFF_NORMED,
      );
      const extrema = runtime.minMaxLoc(correlation);
      const rawConfidence = extrema?.maxVal;
      const variantLeft = extrema?.maxLoc?.x;
      const variantTop = extrema?.maxLoc?.y;
      if (
        typeof rawConfidence !== "number" ||
        !Number.isFinite(rawConfidence) ||
        !Number.isInteger(variantLeft) ||
        !Number.isInteger(variantTop)
      ) {
        invalidMatch = true;
        continue;
      }
      const left = clampedMatchOrigin(
        variantLeft - variant.offsetX,
        backgroundImage.width - puzzleImage.width,
      );
      const top = clampedMatchOrigin(
        variantTop - variant.offsetY,
        backgroundImage.height - puzzleImage.height,
      );
      if (left === null || top === null) {
        invalidMatch = true;
        continue;
      }
      const confidence = Math.max(-1, Math.min(1, rawConfidence));
      if (!edgeBest || confidence > edgeBest.confidence) {
        edgeBest = { confidence, left, top, strategy: variant.name };
      }
    }

    const unambiguousAlphaGap = alphaGap && !alphaGap.ambiguous ? alphaGap : null;
    const unambiguousPhotometric = photometric && !photometric.ambiguous ? photometric : null;
    if (alphaGap?.ambiguous && !unambiguousPhotometric) {
      fail("MATCH_AMBIGUOUS", "multiple image regions contain the same puzzle silhouette");
    }
    if (photometric?.ambiguous && !unambiguousAlphaGap) {
      fail("MATCH_AMBIGUOUS", "multiple image regions match the puzzle texture equally well");
    }
    const best = unambiguousAlphaGap || unambiguousPhotometric || edgeBest;
    if (!templateWithEdges && !best) {
      fail("IMAGE_NO_EDGES", "the supplied images do not contain enough edges to match");
    }
    if (!best) {
      fail(
        "MATCH_RESULT_INVALID",
        invalidMatch
          ? "OpenCV returned no in-bounds template match"
          : "OpenCV returned no usable template match",
      );
    }
    const { confidence, left, top } = best;
    if (confidence < requiredConfidence) {
      fail(
        "MATCH_LOW_CONFIDENCE",
        `match confidence ${confidence.toFixed(3)} is below the required ${requiredConfidence.toFixed(3)}`,
      );
    }

    return Object.freeze({
      algorithm: OPENCV_ALGORITHM,
      confidence,
      targetCenter: Object.freeze({
        x: left + Math.floor(puzzleImage.width / 2),
        y: top + Math.floor(puzzleImage.height / 2),
      }),
      matchBox: Object.freeze({
        x: left,
        y: top,
        width: puzzleImage.width,
        height: puzzleImage.height,
      }),
      background: Object.freeze({ width: backgroundImage.width, height: backgroundImage.height }),
      puzzle: Object.freeze({ width: puzzleImage.width, height: puzzleImage.height }),
    });
  } catch (error) {
    if (error instanceof OpenCvSolverError) throw error;
    throw new OpenCvSolverError(
      "OPENCV_MATCH_FAILED",
      "OpenCV could not match the supplied images",
      { cause: error },
    );
  } finally {
    for (let index = mats.length - 1; index >= 0; index -= 1) safeDelete(mats[index]);
  }
}
