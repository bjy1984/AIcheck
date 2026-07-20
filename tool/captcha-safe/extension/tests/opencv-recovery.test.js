import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const extensionRoot = new URL("../", import.meta.url);

async function createSolverRealm() {
  const [artifact, solverModule] = await Promise.all([
    readFile(new URL("vendor/opencv/opencv.js", extensionRoot), "utf8"),
    readFile(new URL("solver/opencv-solver.js", extensionRoot), "utf8"),
  ]);
  assert.doesNotMatch(solverModule, /^\s*import\s/mu);

  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    performance,
    atob,
    document: { currentScript: null, title: "" },
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  const context = vm.createContext(sandbox, {
    codeGeneration: { strings: false, wasm: true },
  });
  vm.runInContext(artifact, context, { filename: "opencv.js" });
  await new Promise((resolve) => sandbox.cv.then(() => resolve()));

  // Run the exact production module in the OpenCV realm. Removing only ESM
  // export tokens keeps Embind objects on the same global/prototype graph.
  const executableSolver = solverModule.replace(/^export\s+/gmu, "") + `
    globalThis.__solverApi = Object.freeze({
      DEFAULT_MIN_CONFIDENCE,
      solvePuzzleImages,
    });
  `;
  vm.runInContext(executableSolver, context, { filename: "opencv-solver.js" });
  vm.runInContext(FIXTURE_SOURCE, context, { filename: "opencv-recovery-fixtures.js" });
  return context;
}

function jsonFrom(context, expression) {
  return JSON.parse(vm.runInContext(`JSON.stringify(${expression})`, context));
}

const FIXTURE_SOURCE = String.raw`
(() => {
  function image(width, height, gray = 0, alpha = 255) {
    const data = new Uint8ClampedArray(width * height * 4);
    for (let index = 0; index < width * height; index += 1) {
      data[index * 4] = gray;
      data[index * 4 + 1] = gray;
      data[index * 4 + 2] = gray;
      data[index * 4 + 3] = alpha;
    }
    return { width, height, data };
  }

  function pixel(target, x, y, red, green = red, blue = red, alpha = 255) {
    const offset = (y * target.width + x) * 4;
    target.data[offset] = red;
    target.data[offset + 1] = green;
    target.data[offset + 2] = blue;
    target.data[offset + 3] = alpha;
  }

  function transparentTexture() {
    const puzzle = image(27, 23, 0, 0);
    const background = image(100, 52, 118, 255);
    const shapeLeft = 47;
    const shapeTop = 16;
    const paddingX = 5;
    const paddingY = 4;
    function inside(x, y) {
      const base = x >= 5 && x <= 19 && y >= 4 && y <= 17;
      const leftTab = (x - 5) ** 2 + (y - 10) ** 2 <= 16;
      const rightCut = (x - 19) ** 2 + (y - 10) ** 2 < 9;
      const topTab = (x - 12) ** 2 + (y - 4) ** 2 <= 9;
      return (base || leftTab || topTab) && !rightCut;
    }
    for (let y = 0; y < puzzle.height; y += 1) {
      for (let x = 0; x < puzzle.width; x += 1) {
        if (!inside(x, y)) continue;
        const value = (x * 97 + y * 53 + x * y * 31) % 256;
        pixel(puzzle, x, y, value, (value * 3) % 256, 255 - value, 255);
        pixel(background, shapeLeft + x - paddingX, shapeTop + y - paddingY, 55);
      }
    }
    // A plausible second rectangular cutout prevents a trivial single-edge scene.
    for (let y = 8; y < 26; y += 1) {
      for (let x = 10; x < 30; x += 1) {
        if (x === 10 || x === 29 || y === 8 || y === 25) pixel(background, x, y, 50);
      }
    }
    const left = shapeLeft - paddingX;
    const top = shapeTop - paddingY;
    return {
      background,
      puzzle,
      expected: {
        matchBox: { x: left, y: top, width: puzzle.width, height: puzzle.height },
        targetCenter: {
          x: left + Math.floor(puzzle.width / 2),
          y: top + Math.floor(puzzle.height / 2),
        },
      },
    };
  }

  function alphaOnlyOutline() {
    const puzzle = image(30, 25, 0, 0);
    const background = image(104, 54, 124, 255);
    const shapeLeft = 52;
    const shapeTop = 14;
    const paddingX = 6;
    const paddingY = 4;
    function inside(x, y) {
      const base = x >= 6 && x <= 20 && y >= 5 && y <= 18;
      const topTab = (x - 13) ** 2 + (y - 5) ** 2 <= 12;
      const rightCut = (x - 20) ** 2 + (y - 12) ** 2 < 9;
      return (base || topTab) && !rightCut;
    }
    function outline(x, y) {
      if (!inside(x, y)) return false;
      return !inside(x - 1, y) || !inside(x + 1, y) ||
        !inside(x, y - 1) || !inside(x, y + 1);
    }
    for (let y = 0; y < puzzle.height; y += 1) {
      for (let x = 0; x < puzzle.width; x += 1) {
        if (!outline(x, y)) continue;
        // A semi-transparent black outline has no RGB edges. Its alpha channel
        // is the only reliable local representation of the puzzle silhouette.
        pixel(puzzle, x, y, 0, 0, 0, 180);
        pixel(background, shapeLeft + x - paddingX, shapeTop + y - paddingY, 30);
      }
    }
    const left = shapeLeft - paddingX;
    const top = shapeTop - paddingY;
    return {
      background,
      puzzle,
      expected: {
        matchBox: { x: left, y: top, width: puzzle.width, height: puzzle.height },
        targetCenter: {
          x: left + Math.floor(puzzle.width / 2),
          y: top + Math.floor(puzzle.height / 2),
        },
      },
    };
  }

  function paddedCropRequired() {
    const puzzle = image(41, 31, 0, 0);
    const background = image(112, 58, 122, 255);
    const paddingX = 11;
    const paddingY = 7;
    const shapeWidth = 19;
    const shapeHeight = 17;
    const shapeLeft = 53;
    const shapeTop = 17;
    const fullLeft = shapeLeft - paddingX;
    const fullTop = shapeTop - paddingY;
    function inside(x, y) {
      const localX = x - paddingX;
      const localY = y - paddingY;
      const base = localX >= 2 && localX <= 16 && localY >= 2 && localY <= 14;
      const topTab = (localX - 9) ** 2 + (localY - 2) ** 2 <= 9;
      const rightCut = (localX - 16) ** 2 + (localY - 8) ** 2 < 9;
      return (base || topTab) && !rightCut;
    }
    // Texture only the transparent padding area. Full-canvas correlation is
    // intentionally weak while a tight alpha-bounds crop remains matchable.
    for (let y = fullTop; y < fullTop + puzzle.height; y += 1) {
      for (let x = fullLeft; x < fullLeft + puzzle.width; x += 1) {
        const inShapeBox = x >= shapeLeft && x < shapeLeft + shapeWidth &&
          y >= shapeTop && y < shapeTop + shapeHeight;
        if (!inShapeBox) pixel(background, x, y, (x * 13 + y * 29) % 5 < 2 ? 35 : 210);
      }
    }
    for (let y = 0; y < puzzle.height; y += 1) {
      for (let x = 0; x < puzzle.width; x += 1) {
        if (!inside(x, y)) continue;
        pixel(puzzle, x, y, 180, 180, 180, 255);
        pixel(background, shapeLeft + x - paddingX, shapeTop + y - paddingY, 55);
      }
    }
    return {
      background,
      puzzle,
      expected: {
        matchBox: {
          x: fullLeft,
          y: fullTop,
          width: puzzle.width,
          height: puzzle.height,
        },
        targetCenter: {
          x: fullLeft + Math.floor(puzzle.width / 2),
          y: fullTop + Math.floor(puzzle.height / 2),
        },
      },
    };
  }

  function lawyeePhotometric({ ambiguous = false } = {}) {
    const puzzle = image(63, 155, 0, 0);
    const background = image(310, 155, 0, 255);
    const fullLeft = 144;
    const decoyLeft = 36;
    const cropTop = 13;
    const cropBottom = 76;

    function photoTexture(x, y) {
      const grain = ((x * 37 + y * 73 + x * y * 11) % 41) - 20;
      return [
        Math.max(0, Math.min(255, Math.round(
          192 + 24 * Math.sin(x / 13) + 17 * Math.cos(y / 9) + grain,
        ))),
        Math.max(0, Math.min(255, Math.round(
          184 + 19 * Math.cos(x / 17) + 23 * Math.sin((x + y) / 15) - grain / 2,
        ))),
        Math.max(0, Math.min(255, Math.round(
          170 + 22 * Math.sin(x / 21) + 18 * Math.cos((x - y) / 12) + grain / 3,
        ))),
      ];
    }

    function localTexture(x, y) {
      const grain = ((x * 83 + y * 47 + x * y * 19) % 67) - 33;
      return [
        Math.max(0, Math.min(255, Math.round(
          154 + 38 * Math.sin((x + 2 * y) / 7) + 21 * Math.cos(y / 5) + grain,
        ))),
        Math.max(0, Math.min(255, Math.round(
          142 + 34 * Math.cos((2 * x - y) / 9) + 24 * Math.sin(y / 6) - grain / 2,
        ))),
        Math.max(0, Math.min(255, Math.round(
          132 + 31 * Math.sin((x + y) / 8) + 27 * Math.cos(x / 6) + grain / 3,
        ))),
      ];
    }

    function highlighted(channel) {
      return Math.round(0.3 * channel + 0.7 * 255);
    }

    function inside(x, y) {
      const base = x >= 3 && x <= 45 && y >= 32 && y <= 74;
      const topTab = (x - 24) ** 2 + (y - 24) ** 2 <= 81;
      const leftTab = (x - 10) ** 2 + (y - 53) ** 2 <= 64;
      const rightTab = (x - 52) ** 2 + (y - 53) ** 2 <= 81;
      return base || topTab || leftTab || rightTab;
    }

    // The surrounding scene has deterministic, independently varying RGB
    // channels so it behaves like a photograph instead of a flat test card.
    for (let y = 0; y < background.height; y += 1) {
      for (let x = 0; x < background.width; x += 1) {
        pixel(background, x, y, ...photoTexture(x, y));
      }
    }

    // Install the same source-photo crop at every candidate before applying
    // the Lawyee white overlay. In the ambiguous case the two resulting
    // 63x64 search windows are pixel-identical and must not be accepted based
    // on texture correlation alone.
    for (let y = cropTop; y <= cropBottom; y += 1) {
      for (let x = 0; x < puzzle.width; x += 1) {
        const source = localTexture(x, y);
        pixel(background, fullLeft + x, y, ...source);
        if (ambiguous) pixel(background, decoyLeft + x, y, ...source);
      }
    }

    // A distant object boundary crosses the puzzle canvas's transparent
    // lower padding, as happens in a full-height crop of a photograph. It
    // deliberately penalizes legacy full-height edge correlation without
    // affecting the alpha-supported photometric evidence.
    for (let x = 0; x < puzzle.width; x += 1) {
      const seam = x % 6 < 3 ? [72, 83, 96] : [218, 207, 191];
      pixel(background, fullLeft + x, 112, ...seam);
      if (ambiguous) pixel(background, decoyLeft + x, 112, ...seam);
    }

    for (let y = 0; y < puzzle.height; y += 1) {
      for (let x = 0; x < puzzle.width; x += 1) {
        if (!inside(x, y)) continue;
        const source = localTexture(x, y);
        pixel(puzzle, x, y, ...source, 255);
        const gap = source.map(highlighted);
        pixel(background, fullLeft + x, y, ...gap);
        if (ambiguous) pixel(background, decoyLeft + x, y, ...gap);
      }
    }

    return {
      background,
      puzzle,
      expected: {
        alphaCrop: { x: 0, y: cropTop, width: 63, height: 64 },
        matchBox: { x: fullLeft, y: 0, width: 63, height: 155 },
        targetCenter: { x: fullLeft + 31, y: 77 },
        decoyMatchBox: { x: decoyLeft, y: 0, width: 63, height: 155 },
      },
    };
  }

  function vuePuzzleVcodePhotometric() {
    const puzzle = image(101, 360, 0, 0);
    const background = image(720, 360, 0, 255);
    const fullLeft = 340;
    const whiteOverlayAlpha = 0.62;

    function sceneTexture(x, y) {
      let hash = Math.imul(x + 17, 0x45d9f3b) ^ Math.imul(y + 29, 0x119de1f3);
      hash ^= Math.imul(x + 3, y + 11) >>> 0;
      hash ^= hash >>> 16;
      hash = Math.imul(hash, 0x7feb352d);
      hash ^= hash >>> 15;
      hash = Math.imul(hash, 0x846ca68b);
      hash ^= hash >>> 16;
      const grain = (hash & 63) - 31;
      return [
        Math.max(0, Math.min(255, Math.round(
          143 + 35 * Math.sin(x / 23) + 24 * Math.cos(y / 17) + grain,
        ))),
        Math.max(0, Math.min(255, Math.round(
          134 + 29 * Math.cos((x + y) / 27) + 31 * Math.sin(y / 21) - grain / 2,
        ))),
        Math.max(0, Math.min(255, Math.round(
          126 + 32 * Math.sin((2 * x - y) / 31) + 22 * Math.cos(x / 19) + grain / 3,
        ))),
      ];
    }

    function inside(x, y) {
      const base = x >= 13 && x <= 80 && y >= 137 && y <= 218;
      const topTab = (x - 47) ** 2 + (y - 137) ** 2 <= 15 ** 2;
      const rightTab = (x - 80) ** 2 + (y - 177) ** 2 <= 14 ** 2;
      const leftCut = (x - 13) ** 2 + (y - 181) ** 2 < 12 ** 2;
      const bottomCut = (x - 52) ** 2 + (y - 218) ** 2 < 13 ** 2;
      return (base || topTab || rightTab) && !leftCut && !bottomCut;
    }

    function highlighted(channel) {
      return Math.round(
        (1 - whiteOverlayAlpha) * channel + whiteOverlayAlpha * 255,
      );
    }

    // Build one deterministic photographic scene. The puzzle retains the
    // source pixels while its target region receives a translucent white
    // overlay, matching the full-height canvas representation used by
    // vue-puzzle-vcode-style widgets.
    for (let y = 0; y < background.height; y += 1) {
      for (let x = 0; x < background.width; x += 1) {
        pixel(background, x, y, ...sceneTexture(x, y));
      }
    }
    for (let y = 0; y < puzzle.height; y += 1) {
      for (let x = 0; x < puzzle.width; x += 1) {
        if (!inside(x, y)) continue;
        const source = sceneTexture(fullLeft + x, y);
        pixel(puzzle, x, y, ...source, 255);
        pixel(background, fullLeft + x, y, ...source.map(highlighted));
      }
    }

    return {
      background,
      puzzle,
      expected: {
        matchBox: { x: fullLeft, y: 0, width: puzzle.width, height: puzzle.height },
        targetCenter: {
          x: fullLeft + Math.floor(puzzle.width / 2),
          y: Math.floor(puzzle.height / 2),
        },
      },
    };
  }

  function kgCaptchaAlphaGap({ ambiguous = false } = {}) {
    const puzzle = image(72, 180, 126, 0);
    const background = image(360, 180, 126, 255);
    const fullLeft = 122;
    const decoyLeft = 24;

    function inside(x, y) {
      const base = x >= 10 && x <= 60 && y >= 66 && y <= 116;
      const topTab = (x - 35) ** 2 + (y - 66) ** 2 <= 10 ** 2;
      const rightTab = (x - 60) ** 2 + (y - 91) ** 2 <= 10 ** 2;
      const leftCut = (x - 10) ** 2 + (y - 91) ** 2 < 9 ** 2;
      const bottomCut = (x - 35) ** 2 + (y - 116) ** 2 < 9 ** 2;
      return (base || topTab || rightTab) && !leftCut && !bottomCut;
    }

    // Keep every RGB channel flat so neither texture correlation nor Canny
    // edges can solve this fixture. The only target evidence is the weaker
    // copy of the puzzle silhouette in the background PNG's alpha channel.
    for (let y = 0; y < puzzle.height; y += 1) {
      for (let x = 0; x < puzzle.width; x += 1) {
        if (!inside(x, y)) continue;
        const boundary = !inside(x - 1, y) || !inside(x + 1, y) ||
          !inside(x, y - 1) || !inside(x, y + 1);
        const alpha = boundary ? 176 : 255;
        pixel(puzzle, x, y, 126, 126, 126, alpha);
        pixel(background, fullLeft + x, y, 126, 126, 126, 255 - Math.round(alpha / 4));
        if (ambiguous) {
          pixel(background, decoyLeft + x, y, 126, 126, 126, 255 - Math.round(alpha / 4));
        }
      }
    }

    return {
      background,
      puzzle,
      expected: {
        matchBox: { x: fullLeft, y: 0, width: puzzle.width, height: puzzle.height },
        targetCenter: {
          x: fullLeft + Math.floor(puzzle.width / 2),
          y: Math.floor(puzzle.height / 2),
        },
      },
    };
  }

  function unrelatedOpaqueTemplate() {
    const puzzle = image(31, 23, 100, 255);
    const background = image(96, 52, 0, 255);
    let seed = 12345;
    function randomByte() {
      seed = (seed * 1103515245 + 12345) >>> 0;
      return (seed >>> 16) & 255;
    }
    for (let y = 0; y < background.height; y += 1) {
      for (let x = 0; x < background.width; x += 1) pixel(background, x, y, randomByte());
    }
    for (let y = 0; y < puzzle.height; y += 1) {
      for (let x = 0; x < puzzle.width; x += 1) {
        const marked = x === y || x + y === puzzle.width - 1 || (x % 7 === 0 && y % 5 === 0);
        pixel(puzzle, x, y, marked ? 240 : 100);
      }
    }
    return { background, puzzle };
  }

  function rgbaEdges(input) {
    const rgba = new cv.Mat(input.height, input.width, cv.CV_8UC4);
    rgba.data.set(input.data);
    const gray = new cv.Mat();
    const edges = new cv.Mat();
    cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY, 0);
    cv.Canny(gray, edges, 50, 150, 3, false);
    rgba.delete();
    gray.delete();
    return edges;
  }

  function alphaBounds(input) {
    let minimum = 255;
    let maximum = 0;
    let left = input.width;
    let top = input.height;
    let right = -1;
    let bottom = -1;
    for (let y = 0; y < input.height; y += 1) {
      for (let x = 0; x < input.width; x += 1) {
        const alpha = input.data[(y * input.width + x) * 4 + 3];
        minimum = Math.min(minimum, alpha);
        maximum = Math.max(maximum, alpha);
        if (alpha <= 8) continue;
        left = Math.min(left, x);
        top = Math.min(top, y);
        right = Math.max(right, x);
        bottom = Math.max(bottom, y);
      }
    }
    if (minimum === maximum || right < left || bottom < top) return null;
    // Canny needs a small transparent border to retain both sides of a
    // silhouette edge. A crop to the exact non-zero-alpha box clips it.
    const margin = 2;
    left = Math.max(0, left - margin);
    top = Math.max(0, top - margin);
    right = Math.min(input.width - 1, right + margin);
    bottom = Math.min(input.height - 1, bottom + margin);
    return { x: left, y: top, width: right - left + 1, height: bottom - top + 1 };
  }

  function alphaMask(input, bounds = { x: 0, y: 0, width: input.width, height: input.height }) {
    const output = image(bounds.width, bounds.height, 0, 255);
    for (let y = 0; y < bounds.height; y += 1) {
      for (let x = 0; x < bounds.width; x += 1) {
        const source = ((bounds.y + y) * input.width + bounds.x + x) * 4;
        const alpha = input.data[source + 3];
        pixel(output, x, y, alpha, alpha, alpha, 255);
      }
    }
    return output;
  }

  function score(background, template) {
    const backgroundEdges = rgbaEdges(background);
    const templateEdges = rgbaEdges(template);
    let backgroundEdgeCount = 0;
    let templateEdgeCount = 0;
    for (const value of backgroundEdges.data) if (value) backgroundEdgeCount += 1;
    for (const value of templateEdges.data) if (value) templateEdgeCount += 1;
    if (backgroundEdgeCount === 0 || templateEdgeCount === 0) {
      backgroundEdges.delete();
      templateEdges.delete();
      return { confidence: null, backgroundEdgeCount, templateEdgeCount };
    }
    const correlation = new cv.Mat();
    cv.matchTemplate(backgroundEdges, templateEdges, correlation, cv.TM_CCOEFF_NORMED);
    const extrema = cv.minMaxLoc(correlation);
    const result = {
      confidence: extrema.maxVal,
      x: extrema.maxLoc.x,
      y: extrema.maxLoc.y,
      backgroundEdgeCount,
      templateEdgeCount,
    };
    correlation.delete();
    backgroundEdges.delete();
    templateEdges.delete();
    return result;
  }

  const fixtures = Object.freeze({
    transparentTexture: transparentTexture(),
    alphaOnlyOutline: alphaOnlyOutline(),
    paddedCropRequired: paddedCropRequired(),
    lawyeePhotometric: lawyeePhotometric(),
    lawyeePhotometricAmbiguous: lawyeePhotometric({ ambiguous: true }),
    vuePuzzleVcodePhotometric: vuePuzzleVcodePhotometric(),
    kgCaptchaAlphaGap: kgCaptchaAlphaGap(),
    kgCaptchaAlphaGapAmbiguous: kgCaptchaAlphaGap({ ambiguous: true }),
    unrelatedOpaqueTemplate: unrelatedOpaqueTemplate(),
  });

  globalThis.__recoveryFixtures = fixtures;
  globalThis.__measureFixture = (name) => {
    const fixture = fixtures[name];
    const bounds = alphaBounds(fixture.puzzle);
    const baseline = score(fixture.background, fixture.puzzle);
    if (!bounds) return { bounds: null, baseline, alphaFull: null, alphaCrop: null };
    const fullMask = alphaMask(fixture.puzzle);
    const croppedMask = alphaMask(fixture.puzzle, bounds);
    const alphaFull = score(fixture.background, fullMask);
    const alphaCrop = score(fixture.background, croppedMask);
    return { bounds, baseline, alphaFull, alphaCrop };
  };
  globalThis.__solveRecoveryFixtures = () => Object.entries(fixtures).map(([name, fixture]) => {
    try {
      const result = __solverApi.solvePuzzleImages({
        background: fixture.background,
        puzzle: fixture.puzzle,
      }, cv);
      return { name, ok: true, result };
    } catch (error) {
      return { name, ok: false, error: { code: error.code, message: error.message } };
    }
  });
  globalThis.__solveRecoveryFixture = (name) => {
    const fixture = fixtures[name];
    try {
      return {
        name,
        ok: true,
        result: __solverApi.solvePuzzleImages({
          background: fixture.background,
          puzzle: fixture.puzzle,
        }, cv),
      };
    } catch (error) {
      return { name, ok: false, error: { code: error.code, message: error.message } };
    }
  };
})();
`;

test("alpha and cropped-template recovery raises real confidence without lowering the floor", async () => {
  const context = await createSolverRealm();
  const transparent = jsonFrom(context, "__measureFixture('transparentTexture')");
  const outline = jsonFrom(context, "__measureFixture('alphaOnlyOutline')");
  const padded = jsonFrom(context, "__measureFixture('paddedCropRequired')");
  const unrelated = jsonFrom(context, "__measureFixture('unrelatedOpaqueTemplate')");
  const transparentExpected = jsonFrom(context, "__recoveryFixtures.transparentTexture.expected");
  const outlineExpected = jsonFrom(context, "__recoveryFixtures.alphaOnlyOutline.expected");
  const paddedExpected = jsonFrom(context, "__recoveryFixtures.paddedCropRequired.expected");

  assert.ok(transparent.baseline.confidence < 0.5);
  assert.ok(transparent.alphaFull.confidence > 0.95);
  assert.equal(transparent.alphaFull.x, transparentExpected.matchBox.x);
  assert.equal(transparent.alphaFull.y, transparentExpected.matchBox.y);
  assert.equal(outline.baseline.templateEdgeCount, 0);
  assert.ok(outline.alphaFull.confidence > 0.95);
  assert.equal(outline.alphaFull.x, outlineExpected.matchBox.x);
  assert.equal(outline.alphaFull.y, outlineExpected.matchBox.y);
  assert.ok(padded.alphaFull.confidence < 0.5);
  assert.ok(padded.alphaCrop.confidence >= 0.5, JSON.stringify(padded));
  assert.equal(padded.alphaCrop.x - padded.bounds.x, paddedExpected.matchBox.x);
  assert.equal(padded.alphaCrop.y - padded.bounds.y, paddedExpected.matchBox.y);
  assert.equal(unrelated.bounds, null);
  assert.ok(unrelated.baseline.confidence < 0.2);

  const outcomes = jsonFrom(context, "__solveRecoveryFixtures()");
  const recoveredNames = new Set([
    "transparentTexture",
    "alphaOnlyOutline",
    "paddedCropRequired",
  ]);
  const recovered = outcomes.filter((outcome) => recoveredNames.has(outcome.name));
  assert.ok(
    recovered.every((outcome) => outcome.ok),
    `recovery fixtures did not solve at the fixed threshold: ${JSON.stringify(recovered)}`,
  );
  for (const outcome of recovered) {
    const fixture = jsonFrom(context, `__recoveryFixtures[${JSON.stringify(outcome.name)}].expected`);
    assert.ok(outcome.result.confidence >= 0.5);
    assert.deepEqual(outcome.result.matchBox, fixture.matchBox);
    assert.deepEqual(outcome.result.targetCenter, fixture.targetCenter);
  }
  const unrelatedOutcome = outcomes.find((outcome) => outcome.name === "unrelatedOpaqueTemplate");
  assert.equal(unrelatedOutcome.ok, false);
  assert.equal(unrelatedOutcome.error.code, "MATCH_LOW_CONFIDENCE");
});

test("Lawyee photometric gap recovers a tall transparent puzzle at the fixed floor", async () => {
  const context = await createSolverRealm();
  const measured = jsonFrom(context, "__measureFixture('lawyeePhotometric')");
  const expected = jsonFrom(context, "__recoveryFixtures.lawyeePhotometric.expected");
  assert.deepEqual(measured.bounds, expected.alphaCrop);
  assert.ok(measured.baseline.confidence < 0.5);
  assert.ok(measured.alphaFull.confidence < 0.5);
  assert.ok(measured.alphaCrop.confidence < 0.5);

  const outcome = jsonFrom(
    context,
    "__solveRecoveryFixtures().find((item) => item.name === 'lawyeePhotometric')",
  );
  assert.equal(outcome.ok, true, JSON.stringify({ measured, outcome }));
  assert.ok(outcome.result.confidence >= 0.5);
  assert.deepEqual(outcome.result.background, { width: 310, height: 155 });
  assert.deepEqual(outcome.result.puzzle, { width: 63, height: 155 });
  assert.deepEqual(outcome.result.matchBox, expected.matchBox);
  assert.deepEqual(outcome.result.targetCenter, expected.targetCenter);
});

test("Lawyee photometric matching rejects two identical distant candidates", async () => {
  const context = await createSolverRealm();
  const measured = jsonFrom(context, "__measureFixture('lawyeePhotometricAmbiguous')");
  const expected = jsonFrom(context, "__recoveryFixtures.lawyeePhotometricAmbiguous.expected");
  assert.deepEqual(measured.bounds, expected.alphaCrop);
  assert.ok(measured.baseline.confidence < 0.5);
  assert.ok(measured.alphaFull.confidence < 0.5);
  assert.ok(measured.alphaCrop.confidence < 0.5);

  const outcome = jsonFrom(
    context,
    "__solveRecoveryFixtures().find((item) => item.name === 'lawyeePhotometricAmbiguous')",
  );
  assert.equal(outcome.ok, false, JSON.stringify({ measured, outcome }));
  assert.ok(
    ["MATCH_LOW_CONFIDENCE", "MATCH_AMBIGUOUS"].includes(outcome.error.code),
    JSON.stringify(outcome),
  );
});

test("vue-puzzle-vcode-sized photometric gap recovers a full-height transparent puzzle", async () => {
  const context = await createSolverRealm();
  const expected = jsonFrom(
    context,
    "__recoveryFixtures.vuePuzzleVcodePhotometric.expected",
  );
  const outcome = jsonFrom(
    context,
    "__solveRecoveryFixture('vuePuzzleVcodePhotometric')",
  );

  assert.equal(jsonFrom(context, "__solverApi.DEFAULT_MIN_CONFIDENCE"), 0.5);
  assert.equal(outcome.ok, true, JSON.stringify(outcome));
  assert.ok(outcome.result.confidence >= 0.5);
  assert.deepEqual(outcome.result.background, { width: 720, height: 360 });
  assert.deepEqual(outcome.result.puzzle, { width: 101, height: 360 });
  assert.deepEqual(outcome.result.matchBox, expected.matchBox);
  assert.deepEqual(outcome.result.targetCenter, expected.targetCenter);
});

test("kgcaptcha-sized low-texture images match the alpha-encoded target silhouette", async () => {
  const context = await createSolverRealm();
  const measured = jsonFrom(context, "__measureFixture('kgCaptchaAlphaGap')");
  const expected = jsonFrom(context, "__recoveryFixtures.kgCaptchaAlphaGap.expected");
  const outcome = jsonFrom(context, "__solveRecoveryFixture('kgCaptchaAlphaGap')");

  assert.equal(measured.baseline.confidence, null);
  assert.equal(outcome.ok, true, JSON.stringify(outcome));
  assert.ok(outcome.result.confidence >= 0.9);
  assert.deepEqual(outcome.result.background, { width: 360, height: 180 });
  assert.deepEqual(outcome.result.puzzle, { width: 72, height: 180 });
  assert.deepEqual(outcome.result.matchBox, expected.matchBox);
  assert.deepEqual(outcome.result.targetCenter, expected.targetCenter);
});

test("alpha-gap matching rejects two identical distant target silhouettes", async () => {
  const context = await createSolverRealm();
  const outcome = jsonFrom(context, "__solveRecoveryFixture('kgCaptchaAlphaGapAmbiguous')");

  assert.equal(outcome.ok, false, JSON.stringify(outcome));
  assert.equal(outcome.error.code, "MATCH_AMBIGUOUS");
});
