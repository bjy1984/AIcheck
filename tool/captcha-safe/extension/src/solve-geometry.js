const GEOMETRY_POSITION_FIELDS = Object.freeze([
  "backgroundLeft",
  "backgroundTop",
  "puzzleLeft",
  "puzzleTop",
]);

const GEOMETRY_DIMENSION_FIELDS = Object.freeze([
  "backgroundWidth",
  "backgroundHeight",
  "puzzleWidth",
  "puzzleHeight",
  "trackWidth",
  "sliderWidth",
  "devicePixelRatio",
]);

const GEOMETRY_NATURAL_FIELDS = Object.freeze([
  "backgroundNaturalWidth",
  "backgroundNaturalHeight",
]);

const STABLE_GEOMETRY_FIELDS = Object.freeze([
  "backgroundLeft",
  "backgroundTop",
  "backgroundWidth",
  "backgroundHeight",
  "puzzleLeft",
  "puzzleTop",
  "puzzleWidth",
  "puzzleHeight",
  "trackWidth",
  "sliderWidth",
]);

const RECT_FIELDS = Object.freeze(["left", "top", "width", "height"]);
const MOVE_COUNT = 12;
const MOVE_Y_BASE_OFFSETS = Object.freeze([0, 0, 1, 1, 1, 0, 0, -1, -1, 0, 0, 0]);
const MOVE_INTERVAL_WEIGHTS = Object.freeze([
  1.6, 1.35, 1.15, 1, 0.9, 0.85, 0.9, 1, 1.15, 1.35, 1.6,
]);
const UINT32_MAX = 0xffff_ffff;
const ZERO_SEED_STATE = 0x6d2b_79f5;
const MIN_DRAG_DURATION_MS = 320;
const DRAG_DURATION_RANGE_MS = 161;
const PRESS_DURATION_RATIO = 0.22;
const SETTLE_DURATION_RATIO = 0.16;
const MAX_X_JITTER_PX = 1.5;
const MAX_INTERVAL_JITTER_RATIO = 0.08;
const PIXEL_STABILITY_TOLERANCE = 0.5;
const DPR_STABILITY_TOLERANCE = 0.01;
const MOVEMENT_MODEL_SCALED_RANGES = "scaled-ranges";
const MOVEMENT_MODEL_LINKED_OFFSET_LEFT = "linked-offset-left";

export class SolveGeometryError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "SolveGeometryError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new SolveGeometryError(code, message);
}

function requireRecord(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail("GEOMETRY_INVALID", `${label} must be an object`);
  }
  return value;
}

function requireOwn(record, field, label) {
  if (!Object.hasOwn(record, field)) {
    fail("GEOMETRY_INVALID", `${label} is missing ${field}`);
  }
  return record[field];
}

function requireFiniteNumber(value, label, { positive = false } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value) || (positive && value <= 0)) {
    fail(
      "GEOMETRY_INVALID",
      `${label} must be ${positive ? "a positive finite number" : "a finite number"}`,
    );
  }
  return value;
}

function requirePositiveInteger(value, label) {
  if (!Number.isSafeInteger(value) || value <= 0) {
    fail("GEOMETRY_INVALID", `${label} must be a positive integer`);
  }
  return value;
}

function requireIdentity(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    fail("GEOMETRY_INVALID", `${label} must be a non-empty string`);
  }
  return value;
}

function validateGeometry(value) {
  const input = requireRecord(value, "geometry");
  const result = {};
  for (const field of GEOMETRY_POSITION_FIELDS) {
    result[field] = requireFiniteNumber(requireOwn(input, field, "geometry"), `geometry.${field}`);
  }
  for (const field of GEOMETRY_DIMENSION_FIELDS) {
    result[field] = requireFiniteNumber(
      requireOwn(input, field, "geometry"),
      `geometry.${field}`,
      { positive: true },
    );
  }
  for (const field of GEOMETRY_NATURAL_FIELDS) {
    result[field] = requirePositiveInteger(
      requireOwn(input, field, "geometry"),
      `geometry.${field}`,
    );
  }
  return Object.freeze(result);
}

function validateRect(value, label) {
  const input = requireRecord(value, label);
  const result = {};
  for (const field of RECT_FIELDS) {
    result[field] = requireFiniteNumber(
      requireOwn(input, field, label),
      `${label}.${field}`,
      { positive: field === "width" || field === "height" },
    );
  }
  return Object.freeze(result);
}

/**
 * Validate and copy a page-world challenge into a small, immutable descriptor.
 * The identities must be opaque stable strings; this module never interprets
 * them as URLs or page content.
 */
export function validateGeometryDescriptor(value) {
  const input = requireRecord(value, "challenge descriptor");
  const frameId = requireOwn(input, "frameId", "challenge descriptor");
  if (!Number.isSafeInteger(frameId) || frameId < 0) {
    fail("GEOMETRY_INVALID", "challenge descriptor.frameId must be a non-negative integer");
  }
  const movementModel = requireOwn(input, "movementModel", "challenge descriptor");
  if (![MOVEMENT_MODEL_SCALED_RANGES, MOVEMENT_MODEL_LINKED_OFFSET_LEFT]
    .includes(movementModel)) {
    fail("GEOMETRY_INVALID", "challenge descriptor.movementModel is invalid");
  }
  const initialHandleOffsetLeft = requireFiniteNumber(
    requireOwn(input, "initialHandleOffsetLeft", "challenge descriptor"),
    "challenge descriptor.initialHandleOffsetLeft",
  );
  return Object.freeze({
    backgroundIdentity: requireIdentity(
      requireOwn(input, "backgroundIdentity", "challenge descriptor"),
      "challenge descriptor.backgroundIdentity",
    ),
    puzzleIdentity: requireIdentity(
      requireOwn(input, "puzzleIdentity", "challenge descriptor"),
      "challenge descriptor.puzzleIdentity",
    ),
    frameId,
    movementModel,
    initialHandleOffsetLeft,
    geometry: validateGeometry(requireOwn(input, "geometry", "challenge descriptor")),
    handle: validateRect(requireOwn(input, "handle", "challenge descriptor"), "challenge descriptor.handle"),
    track: validateRect(requireOwn(input, "track", "challenge descriptor"), "challenge descriptor.track"),
  });
}

function geometryFrom(value) {
  const input = requireRecord(value, "geometry input");
  if (Object.hasOwn(input, "geometry")) return validateGeometryDescriptor(input).geometry;
  return validateGeometry(input);
}

/** Return the independent natural-to-rendered X and Y scale factors. */
export function validateRenderedNaturalScale(value) {
  const geometry = geometryFrom(value);
  const renderedAspect = geometry.backgroundWidth / geometry.backgroundHeight;
  const naturalAspect = geometry.backgroundNaturalWidth / geometry.backgroundNaturalHeight;
  const aspectRatioDelta = Math.abs(renderedAspect / naturalAspect - 1);
  if (!Number.isFinite(aspectRatioDelta) || aspectRatioDelta > 0.02) {
    fail("BACKGROUND_SCALE_INVALID", "background image appears cropped or non-uniformly scaled");
  }
  return Object.freeze({
    scaleX: geometry.backgroundWidth / geometry.backgroundNaturalWidth,
    scaleY: geometry.backgroundHeight / geometry.backgroundNaturalHeight,
    aspectRatioDelta,
  });
}

function roundTiesToEven(value) {
  const lower = Math.floor(value);
  const fraction = value - lower;
  if (fraction < 0.5) return lower;
  if (fraction > 0.5) return lower + 1;
  return lower % 2 === 0 ? lower : lower + 1;
}

/**
 * Convert an integer center in original background-image pixels to horizontal
 * slider travel, using the measured puzzle and pointer travel ranges.
 */
export function imageTargetCenterToPointerDistance(targetCenterX, value) {
  const input = requireRecord(value, "geometry input");
  const descriptor = Object.hasOwn(input, "geometry") ? validateGeometryDescriptor(input) : null;
  const geometry = descriptor?.geometry || validateGeometry(input);
  if (!Number.isSafeInteger(targetCenterX)) {
    fail("TARGET_CENTER_INVALID", "target center must be an integer image coordinate");
  }
  if (targetCenterX < 0 || targetCenterX >= geometry.backgroundNaturalWidth) {
    fail("TARGET_CENTER_INVALID", "target center is outside the background image");
  }

  const { scaleX } = validateRenderedNaturalScale(geometry);
  const desiredPuzzleCenter = geometry.backgroundLeft + targetCenterX * scaleX;
  const currentPuzzleCenter = geometry.puzzleLeft + geometry.puzzleWidth / 2;
  let desiredPuzzleTravel = desiredPuzzleCenter - currentPuzzleCenter;
  const puzzleTravelRange = geometry.backgroundWidth - geometry.puzzleWidth;
  const pointerTravelRange = geometry.trackWidth - geometry.sliderWidth;
  if (puzzleTravelRange <= 0 || pointerTravelRange <= 0) {
    fail("TRAVEL_RANGE_INVALID", "puzzle or pointer travel range is not positive");
  }
  if (desiredPuzzleTravel < -1 || desiredPuzzleTravel > puzzleTravelRange + 1) {
    fail("TARGET_CENTER_INVALID", "calculated puzzle target is outside the observed travel range");
  }

  desiredPuzzleTravel = Math.min(Math.max(desiredPuzzleTravel, 0), puzzleTravelRange);
  let pointerDistance;
  if (descriptor?.movementModel === MOVEMENT_MODEL_LINKED_OFFSET_LEFT) {
    const desiredPuzzleOffset = desiredPuzzleCenter - geometry.backgroundLeft -
      geometry.puzzleWidth / 2;
    pointerDistance = desiredPuzzleOffset - descriptor.initialHandleOffsetLeft;
  } else {
    pointerDistance = desiredPuzzleTravel * pointerTravelRange / puzzleTravelRange;
  }
  const rounded = roundTiesToEven(pointerDistance);
  if (!Number.isSafeInteger(rounded) || rounded < 0 || rounded > Math.ceil(pointerTravelRange)) {
    fail("TRAVEL_RANGE_INVALID", "calculated pointer distance is outside the track");
  }
  return rounded;
}

function validateImageSize(value, label) {
  const input = requireRecord(value, label);
  return Object.freeze({
    width: requirePositiveInteger(requireOwn(input, "width", label), `${label}.width`),
    height: requirePositiveInteger(requireOwn(input, "height", label), `${label}.height`),
  });
}

/** Bind matcher input dimensions to the browser challenge snapshot. */
export function validateImageDimensions(value, descriptorOrGeometry) {
  const images = requireRecord(value, "matcher images");
  const background = validateImageSize(
    requireOwn(images, "background", "matcher images"),
    "matcher images.background",
  );
  const puzzle = validateImageSize(
    requireOwn(images, "puzzle", "matcher images"),
    "matcher images.puzzle",
  );
  const geometry = geometryFrom(descriptorOrGeometry);

  if (
    background.width !== geometry.backgroundNaturalWidth ||
    background.height !== geometry.backgroundNaturalHeight
  ) {
    fail(
      "IMAGE_DIMENSIONS_MISMATCH",
      "decoded background dimensions do not match the browser challenge",
    );
  }

  const scaleX = geometry.backgroundWidth / background.width;
  const scaleY = geometry.backgroundHeight / background.height;
  const expectedPuzzleWidth = puzzle.width * scaleX;
  const expectedPuzzleHeight = puzzle.height * scaleY;
  const widthTolerance = Math.max(3, expectedPuzzleWidth * 0.15);
  const heightTolerance = Math.max(3, expectedPuzzleHeight * 0.15);
  if (
    Math.abs(expectedPuzzleWidth - geometry.puzzleWidth) > widthTolerance ||
    Math.abs(expectedPuzzleHeight - geometry.puzzleHeight) > heightTolerance
  ) {
    fail(
      "IMAGE_DIMENSIONS_MISMATCH",
      "decoded puzzle dimensions do not match the rendered challenge",
    );
  }

  return Object.freeze({
    expectedPuzzleWidth,
    expectedPuzzleHeight,
    widthTolerance,
    heightTolerance,
  });
}

/** Reject a match whose original-image center row cannot align with the puzzle. */
export function validateVerticalAlignment(targetCenterY, value) {
  const geometry = geometryFrom(value);
  if (!Number.isSafeInteger(targetCenterY)) {
    fail("TARGET_CENTER_INVALID", "target center Y must be an integer image coordinate");
  }
  if (targetCenterY < 0 || targetCenterY >= geometry.backgroundNaturalHeight) {
    fail("TARGET_CENTER_INVALID", "target center Y is outside the background image");
  }
  const scaleY = geometry.backgroundHeight / geometry.backgroundNaturalHeight;
  const matchedCenterY = geometry.backgroundTop + targetCenterY * scaleY;
  const puzzleCenterY = geometry.puzzleTop + geometry.puzzleHeight / 2;
  const errorPx = matchedCenterY - puzzleCenterY;
  const tolerancePx = Math.max(3, geometry.puzzleHeight * 0.15);
  if (Math.abs(errorPx) > tolerancePx) {
    fail("VERTICAL_ALIGNMENT_MISMATCH", "matched target row does not align with the browser puzzle");
  }
  return Object.freeze({ errorPx, tolerancePx });
}

/** Compare only the fields that identify the underlying challenge assets. */
export function sameChallengeIdentity(firstValue, secondValue) {
  const first = validateGeometryDescriptor(firstValue);
  const second = validateGeometryDescriptor(secondValue);
  return first.frameId === second.frameId &&
    first.backgroundIdentity === second.backgroundIdentity &&
    first.puzzleIdentity === second.puzzleIdentity &&
    first.geometry.backgroundNaturalWidth === second.geometry.backgroundNaturalWidth &&
    first.geometry.backgroundNaturalHeight === second.geometry.backgroundNaturalHeight;
}

function rectIsStable(first, second) {
  return RECT_FIELDS.every(
    (field) => Math.abs(first[field] - second[field]) <= PIXEL_STABILITY_TOLERANCE,
  );
}

/** Compare two complete snapshots using the Python runner's 0.5 CSS-pixel bound. */
export function isChallengeStable(firstValue, secondValue) {
  const first = validateGeometryDescriptor(firstValue);
  const second = validateGeometryDescriptor(secondValue);
  if (!sameChallengeIdentity(first, second)) return false;
  return first.movementModel === second.movementModel &&
    Math.abs(first.initialHandleOffsetLeft - second.initialHandleOffsetLeft) <=
      PIXEL_STABILITY_TOLERANCE &&
    STABLE_GEOMETRY_FIELDS.every(
    (field) => Math.abs(first.geometry[field] - second.geometry[field]) <=
      PIXEL_STABILITY_TOLERANCE,
  ) &&
    Math.abs(first.geometry.devicePixelRatio - second.geometry.devicePixelRatio) <=
      DPR_STABILITY_TOLERANCE &&
    rectIsStable(first.handle, second.handle) &&
    rectIsStable(first.track, second.track);
}

function createXorshift32(seed) {
  let state = seed === 0 ? ZERO_SEED_STATE : seed;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    state >>>= 0;
    return state;
  };
}

function unitRandom(nextUint32) {
  return nextUint32() / (UINT32_MAX + 1);
}

function smoothstep(progress) {
  return progress * progress * (3 - 2 * progress);
}

function moveYOffsets(variant) {
  const source = (variant & 1) === 0
    ? MOVE_Y_BASE_OFFSETS
    : [...MOVE_Y_BASE_OFFSETS].reverse();
  const direction = (variant & 2) === 0 ? 1 : -1;
  return source.map((offset) => offset * direction);
}

function normalizedIntegerDurations(totalMs, weights) {
  const weightTotal = weights.reduce((sum, weight) => sum + weight, 0);
  const exact = weights.map((weight) => totalMs * weight / weightTotal);
  const durations = exact.map(Math.floor);
  let remaining = totalMs - durations.reduce((sum, duration) => sum + duration, 0);
  const remainderOrder = exact
    .map((duration, index) => ({ fraction: duration - durations[index], index }))
    .sort((first, second) => second.fraction - first.fraction || first.index - second.index);
  for (let index = 0; index < remaining; index += 1) {
    durations[remainderOrder[index].index] += 1;
  }
  return durations;
}

/** Build a deterministic spatial and temporal CDP drag plan from one uint32 seed. */
export function createCdpDragPlan(handleValue, pointerDistancePx, seed) {
  const handle = validateRect(handleValue, "handle");
  if (!Number.isSafeInteger(pointerDistancePx) || pointerDistancePx < 0) {
    fail("DRAG_PLAN_INVALID", "pointer distance must be a non-negative integer");
  }
  if (!Number.isSafeInteger(seed) || seed < 0 || seed > UINT32_MAX) {
    fail("DRAG_PLAN_INVALID", "drag seed must be a uint32 integer");
  }
  const startX = handle.left + handle.width / 2;
  const startY = handle.top + handle.height / 2;
  const endX = startX + pointerDistancePx;
  if (![startX, startY, endX].every(Number.isFinite)) {
    fail("DRAG_PLAN_INVALID", "drag coordinates are not finite");
  }

  const nextUint32 = createXorshift32(seed);
  const totalDurationMs = MIN_DRAG_DURATION_MS +
    Math.floor(unitRandom(nextUint32) * DRAG_DURATION_RANGE_MS);
  const yOffsets = moveYOffsets(nextUint32() % 4);

  const events = [{
    type: "mousePressed",
    x: startX,
    y: startY,
    button: "left",
    buttons: 1,
    clickCount: 1,
  }];
  let previousTravel = 0;
  for (let index = 1; index < MOVE_COUNT; index += 1) {
    const baseTravel = pointerDistancePx * smoothstep(index / MOVE_COUNT);
    const jitter = (unitRandom(nextUint32) * 2 - 1) * MAX_X_JITTER_PX;
    const travel = Math.min(
      pointerDistancePx,
      Math.max(previousTravel, baseTravel + jitter),
    );
    events.push({
      type: "mouseMoved",
      x: startX + travel,
      y: startY + yOffsets[index - 1],
      button: "left",
      buttons: 1,
    });
    previousTravel = travel;
  }
  events.push({
    type: "mouseMoved",
    x: endX,
    y: startY + yOffsets[MOVE_COUNT - 1],
    button: "left",
    buttons: 1,
  });
  events.push({
    type: "mouseReleased",
    x: endX,
    y: startY,
    button: "left",
    buttons: 0,
    clickCount: 1,
  });

  const pressDurationMs = Math.round(totalDurationMs * PRESS_DURATION_RATIO);
  const settleDurationMs = Math.round(totalDurationMs * SETTLE_DURATION_RATIO);
  const moveDurationMs = totalDurationMs - pressDurationMs - settleDurationMs;
  const intervalWeights = MOVE_INTERVAL_WEIGHTS.map((weight) => (
    weight * (
      1 + (unitRandom(nextUint32) * 2 - 1) * MAX_INTERVAL_JITTER_RATIO
    )
  ));
  const moveDurationsMs = normalizedIntegerDurations(moveDurationMs, intervalWeights);
  const delaysMs = Object.freeze([
    pressDurationMs,
    ...moveDurationsMs,
    settleDurationMs,
    0,
  ]);
  const frozenEvents = Object.freeze(events.map((event) => Object.freeze(event)));
  return Object.freeze({ events: frozenEvents, delaysMs });
}
