import assert from "node:assert/strict";
import test from "node:test";

import {
  SolveGeometryError,
  createCdpDragPlan,
  imageTargetCenterToPointerDistance,
  isChallengeStable,
  sameChallengeIdentity,
  validateGeometryDescriptor,
  validateImageDimensions,
  validateRenderedNaturalScale,
  validateVerticalAlignment,
} from "../src/solve-geometry.js";

function descriptor(overrides = {}) {
  const geometry = {
    backgroundLeft: 100,
    backgroundTop: 50,
    backgroundWidth: 300,
    backgroundHeight: 150,
    backgroundNaturalWidth: 600,
    backgroundNaturalHeight: 300,
    puzzleLeft: 100,
    puzzleTop: 50,
    puzzleWidth: 50,
    puzzleHeight: 50,
    trackWidth: 300,
    sliderWidth: 50,
    devicePixelRatio: 2,
    ...overrides.geometry,
  };
  return {
    backgroundIdentity: "background:sha256:abc",
    puzzleIdentity: "puzzle:sha256:def",
    frameId: 0,
    movementModel: "scaled-ranges",
    initialHandleOffsetLeft: 0,
    geometry,
    handle: { left: 10, top: 200, width: 50, height: 50, ...overrides.handle },
    track: { left: 10, top: 200, width: 300, height: 50, ...overrides.track },
    ...Object.fromEntries(
      Object.entries(overrides).filter(([key]) => !["geometry", "handle", "track"].includes(key)),
    ),
  };
}

function expectCode(code) {
  return (error) => error instanceof SolveGeometryError && error.code === code;
}

test("validates and deeply copies the canonical geometry descriptor", () => {
  const source = descriptor();
  const result = validateGeometryDescriptor(source);
  assert.notEqual(result, source);
  assert.deepEqual(result, source);
  assert.equal(Object.isFrozen(result), true);
  assert.equal(Object.isFrozen(result.geometry), true);
  assert.equal(Object.isFrozen(result.handle), true);
  assert.equal(Object.isFrozen(result.track), true);

  source.geometry.backgroundWidth = 1;
  assert.equal(result.geometry.backgroundWidth, 300);
});

test("rejects incomplete, non-finite, fractional-natural, and non-positive geometry", () => {
  const missing = descriptor();
  delete missing.geometry.trackWidth;
  assert.throws(() => validateGeometryDescriptor(missing), expectCode("GEOMETRY_INVALID"));
  assert.throws(
    () => validateGeometryDescriptor(descriptor({ geometry: { puzzleLeft: Number.NaN } })),
    expectCode("GEOMETRY_INVALID"),
  );
  assert.throws(
    () => validateGeometryDescriptor(descriptor({ geometry: { backgroundNaturalWidth: 600.5 } })),
    expectCode("GEOMETRY_INVALID"),
  );
  assert.throws(
    () => validateGeometryDescriptor(descriptor({ geometry: { trackWidth: 0 } })),
    expectCode("GEOMETRY_INVALID"),
  );
  assert.throws(
    () => validateGeometryDescriptor(descriptor({ handle: { width: false } })),
    expectCode("GEOMETRY_INVALID"),
  );
  assert.throws(
    () => validateGeometryDescriptor(descriptor({ movementModel: "unknown" })),
    expectCode("GEOMETRY_INVALID"),
  );
  assert.throws(
    () => validateGeometryDescriptor(descriptor({ frameId: -1 })),
    expectCode("GEOMETRY_INVALID"),
  );
});

test("converts original-image center coordinates through measured travel ranges", () => {
  assert.equal(imageTargetCenterToPointerDistance(300, descriptor()), 125);
  assert.equal(
    imageTargetCenterToPointerDistance(300, descriptor({ geometry: { puzzleLeft: 110 } })),
    115,
  );

  // Preserve Python round(): exact halves round to the nearest even integer.
  const halfDistance = descriptor({
    geometry: {
      backgroundLeft: 0,
      backgroundWidth: 102,
      backgroundHeight: 51,
      backgroundNaturalWidth: 102,
      backgroundNaturalHeight: 51,
      puzzleLeft: 0,
      puzzleWidth: 2,
      trackWidth: 103,
      sliderWidth: 2,
    },
  });
  assert.equal(imageTargetCenterToPointerDistance(51, halfDistance), 50);
});

test("direct full-height image overlays preserve one-to-one handle movement", () => {
  const kgCaptcha = descriptor({
    movementModel: "linked-offset-left",
    initialHandleOffsetLeft: -1,
    geometry: {
      backgroundLeft: 100,
      backgroundTop: 40,
      backgroundWidth: 360,
      backgroundHeight: 180,
      backgroundNaturalWidth: 360,
      backgroundNaturalHeight: 180,
      puzzleLeft: 100,
      puzzleTop: 40,
      puzzleWidth: 72,
      puzzleHeight: 180,
      trackWidth: 360,
      sliderWidth: 52,
    },
    handle: { left: 99, top: 235, width: 52, height: 45 },
    track: { left: 100, top: 235, width: 360, height: 45 },
  });

  // matchBox.x=122 -> targetCenter.x=158. The handle begins at -1, so the
  // pointer travels 123 CSS px and the linked piece finishes exactly at 122.
  assert.equal(imageTargetCenterToPointerDistance(158, kgCaptcha), 123);
});

test("enforces target bounds, positive travel, and the 2 percent aspect bound", () => {
  assert.throws(
    () => imageTargetCenterToPointerDistance(-1, descriptor()),
    expectCode("TARGET_CENTER_INVALID"),
  );
  assert.throws(
    () => imageTargetCenterToPointerDistance(1.5, descriptor()),
    expectCode("TARGET_CENTER_INVALID"),
  );
  assert.throws(
    () => imageTargetCenterToPointerDistance(300, descriptor({ geometry: { sliderWidth: 300 } })),
    expectCode("TRAVEL_RANGE_INVALID"),
  );
  assert.throws(
    () => imageTargetCenterToPointerDistance(300, descriptor({ geometry: { backgroundHeight: 140 } })),
    expectCode("BACKGROUND_SCALE_INVALID"),
  );

  const insideBoundary = descriptor({ geometry: { backgroundHeight: 300 / (2 * 0.9801) } });
  assert.ok(validateRenderedNaturalScale(insideBoundary).aspectRatioDelta < 0.02);
});

test("binds decoded background and puzzle dimensions to browser geometry", () => {
  assert.deepEqual(
    validateImageDimensions(
      { background: { width: 600, height: 300 }, puzzle: { width: 100, height: 100 } },
      descriptor(),
    ),
    {
      expectedPuzzleWidth: 50,
      expectedPuzzleHeight: 50,
      widthTolerance: 7.5,
      heightTolerance: 7.5,
    },
  );
  assert.throws(
    () => validateImageDimensions(
      { background: { width: 1200, height: 300 }, puzzle: { width: 100, height: 100 } },
      descriptor(),
    ),
    expectCode("IMAGE_DIMENSIONS_MISMATCH"),
  );
  assert.throws(
    () => validateImageDimensions(
      { background: { width: 600, height: 300 }, puzzle: { width: 100, height: 100 } },
      descriptor({ geometry: { puzzleWidth: 20 } }),
    ),
    expectCode("IMAGE_DIMENSIONS_MISMATCH"),
  );

  // Small pieces use the absolute 3 CSS-pixel tolerance instead of 15%.
  validateImageDimensions(
    { background: { width: 600, height: 300 }, puzzle: { width: 20, height: 20 } },
    descriptor({ geometry: { puzzleWidth: 13, puzzleHeight: 7 } }),
  );
});

test("validates vertical alignment in rendered CSS pixels", () => {
  assert.deepEqual(validateVerticalAlignment(50, descriptor()), { errorPx: 0, tolerancePx: 7.5 });
  assert.throws(
    () => validateVerticalAlignment(100, descriptor()),
    expectCode("VERTICAL_ALIGNMENT_MISMATCH"),
  );
  assert.throws(
    () => validateVerticalAlignment(300, descriptor()),
    expectCode("TARGET_CENTER_INVALID"),
  );
});

test("compares challenge identity separately from 0.5 CSS-pixel stability", () => {
  const first = descriptor();
  assert.equal(sameChallengeIdentity(first, descriptor()), true);
  assert.equal(sameChallengeIdentity(first, descriptor({ frameId: 2 })), false);
  assert.equal(
    sameChallengeIdentity(first, descriptor({ backgroundIdentity: "background:sha256:changed" })),
    false,
  );
  assert.equal(
    sameChallengeIdentity(
      first,
      descriptor({ geometry: { backgroundNaturalWidth: 601 } }),
    ),
    false,
  );

  assert.equal(
    isChallengeStable(first, descriptor({ geometry: { backgroundLeft: 100.5 }, handle: { left: 10.5 } })),
    true,
  );
  assert.equal(
    isChallengeStable(first, descriptor({ geometry: { backgroundLeft: 100.500001 } })),
    false,
  );
  assert.equal(isChallengeStable(first, descriptor({ track: { top: 200.500001 } })), false);
  assert.equal(
    isChallengeStable(first, descriptor({ geometry: { devicePixelRatio: 2.010001 } })),
    false,
  );
});

test("creates a stable drag-plan snapshot for a fixed seed", () => {
  const plan = createCdpDragPlan(
    { left: 10, top: 20, width: 40, height: 20 },
    120,
    0x1234_5678,
  );
  assert.deepEqual(
    plan.events.map((event) => ({
      type: event.type,
      x: Number(event.x.toFixed(6)),
      y: event.y,
      buttons: event.buttons,
    })),
    [
      { type: "mousePressed", x: 30, y: 30, buttons: 1 },
      { type: "mouseMoved", x: 31.70637, y: 30, buttons: 1 },
      { type: "mouseMoved", x: 38.908832, y: 30, buttons: 1 },
      { type: "mouseMoved", x: 48.565156, y: 30, buttons: 1 },
      { type: "mouseMoved", x: 60.099311, y: 31, buttons: 1 },
      { type: "mouseMoved", x: 75.253619, y: 31, buttons: 1 },
      { type: "mouseMoved", x: 90.809712, y: 30, buttons: 1 },
      { type: "mouseMoved", x: 105.839278, y: 30, buttons: 1 },
      { type: "mouseMoved", x: 118.076692, y: 29, buttons: 1 },
      { type: "mouseMoved", x: 130.989223, y: 29, buttons: 1 },
      { type: "mouseMoved", x: 140.525867, y: 29, buttons: 1 },
      { type: "mouseMoved", x: 149.100729, y: 30, buttons: 1 },
      { type: "mouseMoved", x: 150, y: 30, buttons: 1 },
      { type: "mouseReleased", x: 150, y: 30, buttons: 0 },
    ],
  );
  assert.deepEqual(plan.delaysMs, [89, 29, 26, 24, 20, 19, 17, 17, 18, 24, 25, 32, 65, 0]);
  assert.deepEqual(plan.events[0], {
    type: "mousePressed", x: 30, y: 30, button: "left", buttons: 1, clickCount: 1,
  });
  assert.deepEqual(plan.events[13], {
    type: "mouseReleased", x: 150, y: 30, button: "left", buttons: 0, clickCount: 1,
  });
  assert.equal(Object.isFrozen(plan), true);
  assert.equal(Object.isFrozen(plan.events), true);
  assert.equal(Object.isFrozen(plan.delaysMs), true);
  assert.equal(plan.events.every(Object.isFrozen), true);
  assert.deepEqual(
    createCdpDragPlan({ left: 10, top: 20, width: 40, height: 20 }, 120, 0x1234_5678),
    plan,
  );
});

test("keeps spatial and temporal invariants across 1024 seeds and three distances", () => {
  const handle = { left: 10, top: 20, width: 40, height: 20 };
  const startX = 30;
  const startY = 30;
  const distances = [0, 1, 120];
  const baseYOffsets = [0, 0, 1, 1, 1, 0, 0, -1, -1, 0, 0, 0];
  const reversedYOffsets = [...baseYOffsets].reverse();
  const allowedYVariants = new Set([
    baseYOffsets,
    reversedYOffsets,
    baseYOffsets.map((value) => -value),
    reversedYOffsets.map((value) => -value),
  ].map(JSON.stringify));
  let minimumObservedDuration = Number.POSITIVE_INFINITY;
  let maximumObservedDuration = 0;
  const observedYVariants = new Set();

  for (let seedIndex = 0; seedIndex < 1024; seedIndex += 1) {
    const seed = Math.imul(seedIndex, 0x9e37_79b9) >>> 0;
    for (const distance of distances) {
      const { events, delaysMs } = createCdpDragPlan(handle, distance, seed);
      const moves = events.slice(1, 13);
      assert.equal(events.length, 14);
      assert.equal(delaysMs.length, 14);
      assert.equal(events[0].type, "mousePressed");
      assert.equal(events[13].type, "mouseReleased");
      assert.equal(events[0].x, startX);
      assert.equal(events[0].y, startY);
      assert.equal(moves[11].x, startX + distance);
      assert.equal(events[13].x, startX + distance);
      assert.equal(events[13].y, startY);

      let previousX = startX;
      for (let moveIndex = 0; moveIndex < moves.length; moveIndex += 1) {
        const event = moves[moveIndex];
        assert.ok(Number.isFinite(event.x));
        assert.ok(event.x >= previousX);
        assert.ok(event.x <= startX + distance);
        if (moveIndex < 11) {
          const progress = (moveIndex + 1) / 12;
          const smoothstep = progress * progress * (3 - 2 * progress);
          const perturbation = event.x - startX - distance * smoothstep;
          assert.ok(Math.abs(perturbation) <= 1.5 + Number.EPSILON * 16);
        }
        previousX = event.x;
      }

      const yOffsets = moves.map((event) => event.y - startY);
      observedYVariants.add(JSON.stringify(yOffsets));
      assert.equal(allowedYVariants.has(JSON.stringify(yOffsets)), true);
      assert.ok(Math.max(...yOffsets.map(Math.abs)) <= 1);
      const meanY = yOffsets.reduce((sum, value) => sum + value, 0) / yOffsets.length;
      const yStandardDeviation = Math.sqrt(
        yOffsets.reduce((sum, value) => sum + (value - meanY) ** 2, 0) /
          yOffsets.length,
      );
      assert.ok(yStandardDeviation > 0);

      assert.equal(delaysMs.at(-1), 0);
      assert.equal(delaysMs.every((delay) => Number.isSafeInteger(delay) && delay >= 0), true);
      const totalDurationMs = delaysMs.reduce((sum, delay) => sum + delay, 0);
      minimumObservedDuration = Math.min(minimumObservedDuration, totalDurationMs);
      maximumObservedDuration = Math.max(maximumObservedDuration, totalDurationMs);
      assert.ok(totalDurationMs >= 320 && totalDurationMs <= 480);
      assert.ok(Math.abs(delaysMs[0] - totalDurationMs * 0.22) <= 0.5);
      assert.ok(Math.abs(delaysMs[12] - totalDurationMs * 0.16) <= 0.5);
      assert.ok(delaysMs[1] > delaysMs[6]);
      assert.ok(delaysMs[11] > delaysMs[6]);
    }
  }

  assert.equal(minimumObservedDuration, 320);
  assert.equal(maximumObservedDuration, 480);
  assert.equal(observedYVariants.size, 4);
  assert.deepEqual(
    createCdpDragPlan(handle, 120, 0),
    createCdpDragPlan(handle, 120, 0x6d2b_79f5),
  );
});

test("rejects invalid pointer distances and non-uint32 seeds", () => {
  assert.throws(
    () => createCdpDragPlan({ left: 0, top: 0, width: 10, height: 10 }, -1, 1),
    expectCode("DRAG_PLAN_INVALID"),
  );
  assert.throws(
    () => createCdpDragPlan({ left: 0, top: 0, width: 10, height: 10 }, 1.5, 1),
    expectCode("DRAG_PLAN_INVALID"),
  );
  for (const invalidSeed of [-1, 0x1_0000_0000, 1.5, Number.NaN, "1", undefined, null]) {
    assert.throws(
      () => createCdpDragPlan(
        { left: 0, top: 0, width: 10, height: 10 },
        1,
        invalidSeed,
      ),
      expectCode("DRAG_PLAN_INVALID"),
    );
  }
});
