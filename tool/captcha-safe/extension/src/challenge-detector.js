// Both exported functions are passed directly to chrome.scripting.executeScript.
// Keep each function self-contained: serialized injected functions cannot use
// imports, module constants, or helpers from the extension service worker.

export function detectPageChallenge() {
  const errorResult = (code, message) => ({
    ok: false,
    error: { code, message },
  });

  try {
    const documentObject = globalThis.document;
    const styleFor = globalThis.getComputedStyle;
    if (!documentObject || typeof styleFor !== "function") {
      return errorResult("CHALLENGE_SCAN_UNAVAILABLE", "page layout APIs are unavailable");
    }

    const viewportWidth = Number(globalThis.innerWidth);
    const viewportHeight = Number(globalThis.innerHeight);
    if (!Number.isFinite(viewportWidth) || viewportWidth <= 0 ||
        !Number.isFinite(viewportHeight) || viewportHeight <= 0) {
      return errorResult("CHALLENGE_SCAN_UNAVAILABLE", "page viewport is unavailable");
    }

    const MAX_NODES = 6000;
    const MAX_CANDIDATES_PER_STAGE = 96;
    const MIN_SCORE = 25;
    const AMBIGUITY_SCORE_DELTA = 3;
    const SHADOW_TOKEN = "shadow";
    const challengeWords = /captcha|challenge|human|robot|puzzle|jigsaw|slider|slide|drag|swipe|verify|verification|security|unlock|imgscode|code-k-div|拼图|滑块|拖动|验证|验证码|人机|安全/iu;
    const handleWords = /handle|thumb|knob|grab|grip|slider|slide|drag|swipe|move|code-btn-img|滑块|拖动|按住/iu;
    const trackWords = /track|rail|bar|slider|slide|drag|swipe|progress|verify|code-btn(?:\s|$)|轨道|滑道|滑块|拖动|验证/iu;
    const backgroundWords = /background|backdrop|canvas|image|picture|captcha|challenge|puzzle|jigsaw|code-back-img|背景|底图|拼图|验证码/iu;
    const pieceWords = /piece|jigsaw|puzzle|slice|cutout|shadow|block|template|mask|fragment|code-front-img|拼图|缺口|碎片/iu;
    const pieceControlWords = /refresh|reload|reset|retry|control|toolbar|close|cancel|刷新|重载|重置|重试|关闭|取消/iu;
    const iconWords = /icon|glyph|sprite|图标/iu;

    const round = (value) => Math.round(value * 1000) / 1000;
    const rectOf = (element) => {
      const raw = element?.getBoundingClientRect?.();
      if (!raw) return null;
      const values = [raw.left, raw.top, raw.width, raw.height].map(Number);
      if (!values.every(Number.isFinite) || values[2] <= 0 || values[3] <= 0) return null;
      return {
        left: round(values[0]),
        top: round(values[1]),
        width: round(values[2]),
        height: round(values[3]),
      };
    };
    const right = (rect) => rect.left + rect.width;
    const bottom = (rect) => rect.top + rect.height;
    const centerX = (rect) => rect.left + rect.width / 2;
    const centerY = (rect) => rect.top + rect.height / 2;
    const overlap = (startA, endA, startB, endB) =>
      Math.max(0, Math.min(endA, endB) - Math.max(startA, startB));
    const horizontalOverlap = (a, b) => overlap(a.left, right(a), b.left, right(b));
    const verticalOverlap = (a, b) => overlap(a.top, bottom(a), b.top, bottom(b));
    const intersectionOverUnion = (a, b) => {
      const area = horizontalOverlap(a, b) * verticalOverlap(a, b);
      const union = a.width * a.height + b.width * b.height - area;
      return union > 0 ? area / union : 0;
    };
    const inViewport = (rect) => right(rect) > 0 && bottom(rect) > 0 &&
      rect.left < viewportWidth && rect.top < viewportHeight;
    const stringValue = (value) => {
      if (typeof value === "string") return value;
      if (value && typeof value.baseVal === "string") return value.baseVal;
      return "";
    };
    const attribute = (element, name) => {
      try {
        return stringValue(element.getAttribute?.(name));
      } catch {
        return "";
      }
    };
    const semanticText = (element) => {
      const tagName = stringValue(element?.tagName).toLowerCase();
      const values = [
        tagName,
        stringValue(element?.id),
        stringValue(element?.className),
        attribute(element, "role"),
        attribute(element, "aria-label"),
        attribute(element, "title"),
        attribute(element, "alt"),
        attribute(element, "name"),
        attribute(element, "data-role"),
        attribute(element, "data-testid"),
      ];
      if (tagName === "button" || attribute(element, "role") === "button" ||
          attribute(element, "role") === "slider") {
        values.push(stringValue(element?.textContent).slice(0, 96));
      }
      return values.join(" ").replace(/\s+/gu, " ").trim().slice(0, 512);
    };
    const parentAcrossRoots = (element) => {
      if (element?.parentElement) return element.parentElement;
      try {
        return element?.getRootNode?.()?.host || null;
      } catch {
        return null;
      }
    };
    const ancestors = (element, maximum = 10) => {
      const values = [];
      let current = parentAcrossRoots(element);
      while (current && values.length < maximum) {
        values.push(current);
        current = parentAcrossRoots(current);
      }
      return values;
    };
    const ancestorContext = (element) => ancestors(element, 5)
      .map(semanticText).join(" ").slice(0, 1024);
    const sharedAncestorStrength = (leftElement, rightElement) => {
      const leftAncestors = [leftElement, ...ancestors(leftElement, 10)];
      const rightAncestors = [rightElement, ...ancestors(rightElement, 10)];
      for (let leftIndex = 0; leftIndex < leftAncestors.length; leftIndex += 1) {
        const rightIndex = rightAncestors.indexOf(leftAncestors[leftIndex]);
        if (rightIndex >= 0) return Math.max(0, 5 - Math.floor((leftIndex + rightIndex) / 2));
      }
      return 0;
    };
    const resourceOf = (element, computedStyle) => {
      const tagName = stringValue(element?.tagName).toLowerCase();
      if (tagName === "img") {
        const url = stringValue(element.currentSrc) || stringValue(element.src) ||
          attribute(element, "src") || null;
        const naturalWidth = Number(element.naturalWidth);
        const naturalHeight = Number(element.naturalHeight);
        return {
          kind: "img",
          url,
          naturalWidth: Number.isFinite(naturalWidth) && naturalWidth > 0
            ? Math.round(naturalWidth) : null,
          naturalHeight: Number.isFinite(naturalHeight) && naturalHeight > 0
            ? Math.round(naturalHeight) : null,
        };
      }
      if (tagName === "canvas") {
        const naturalWidth = Number(element.width);
        const naturalHeight = Number(element.height);
        return {
          kind: "canvas",
          url: null,
          naturalWidth: Number.isFinite(naturalWidth) && naturalWidth > 0
            ? Math.round(naturalWidth) : null,
          naturalHeight: Number.isFinite(naturalHeight) && naturalHeight > 0
            ? Math.round(naturalHeight) : null,
        };
      }
      const backgroundImage = stringValue(computedStyle?.backgroundImage);
      const match = backgroundImage.match(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*?))\s*\)/iu);
      if (match) {
        const url = (match[1] ?? match[2] ?? match[3] ?? "").trim() || null;
        return {
          kind: "css",
          url,
          naturalWidth: null,
          naturalHeight: null,
        };
      }
      return { kind: "none", url: null, naturalWidth: null, naturalHeight: null };
    };
    const visibleInfo = (element, path) => {
      const rect = rectOf(element);
      if (!rect || !inViewport(rect)) return null;
      let style;
      try {
        style = styleFor(element);
      } catch {
        return null;
      }
      const display = stringValue(style?.display).toLowerCase();
      const visibility = stringValue(style?.visibility).toLowerCase();
      const opacityText = stringValue(style?.opacity);
      const opacity = opacityText === "" ? 1 : Number(opacityText);
      if (display === "none" || visibility === "hidden" || visibility === "collapse" ||
          (Number.isFinite(opacity) && opacity <= 0.01)) return null;
      const semantic = semanticText(element);
      return {
        element,
        rect,
        path,
        semantic,
        context: `${semantic} ${ancestorContext(element)}`.slice(0, 1536),
        role: attribute(element, "role").toLowerCase(),
        tagName: stringValue(element.tagName).toLowerCase(),
        cursor: stringValue(style?.cursor).toLowerCase(),
        draggable: attribute(element, "draggable").toLowerCase() === "true" ||
          element.draggable === true,
        resource: resourceOf(element, style),
      };
    };

    const nodes = [];
    let visitedNodeCount = 0;
    let scanTruncated = false;
    const walk = (root, basePath) => {
      if (visitedNodeCount >= MAX_NODES) {
        scanTruncated = true;
        return;
      }
      let children;
      try {
        children = Array.from(root?.children || []);
      } catch {
        return;
      }
      for (let index = 0; index < children.length; index += 1) {
        if (visitedNodeCount >= MAX_NODES) {
          scanTruncated = true;
          return;
        }
        visitedNodeCount += 1;
        const element = children[index];
        const path = [...basePath, index];
        const info = visibleInfo(element, path);
        if (info) nodes.push(info);
        let shadowRoot = null;
        try {
          shadowRoot = element.shadowRoot;
        } catch {
          shadowRoot = null;
        }
        if (shadowRoot) walk(shadowRoot, [...path, SHADOW_TOKEN]);
        walk(element, path);
      }
    };
    walk(documentObject, []);
    if (scanTruncated) {
      return errorResult("CHALLENGE_SCAN_LIMIT", "page contains too many elements to scan safely");
    }

    const infoByElement = new Map(nodes.map((info) => [info.element, info]));
    const locatorOf = (info) => ({ version: 1, path: [...info.path] });
    const interactive = (info) => info.tagName === "button" || info.tagName === "input" ||
      info.role === "button" || info.role === "slider" || info.draggable ||
      /pointer|grab|grabbing|move/iu.test(info.cursor);
    const handleCandidates = nodes.map((info) => {
      const rect = info.rect;
      if (rect.width < 16 || rect.height < 16 || rect.width > 140 || rect.height > 140 ||
          rect.width / rect.height < 0.3 || rect.width / rect.height > 3.3) return null;
      const ownHandleWord = handleWords.test(info.semantic);
      const roleSlider = info.role === "slider";
      if (!ownHandleWord && !roleSlider && !info.draggable &&
          !(interactive(info) && challengeWords.test(info.context))) return null;
      let score = 0;
      if (ownHandleWord) score += 6;
      if (roleSlider) score += 7;
      if (info.draggable) score += 3;
      if (interactive(info)) score += 2;
      if (challengeWords.test(info.context)) score += 2;
      if (rect.width / rect.height >= 0.65 && rect.width / rect.height <= 1.55) score += 2;
      return { info, score };
    }).filter(Boolean).sort((a, b) => b.score - a.score).slice(0, MAX_CANDIDATES_PER_STAGE);

    const backgroundCandidates = nodes.map((info) => {
      const rect = info.rect;
      const hasResource = info.resource.kind !== "none";
      const namedBackground = backgroundWords.test(info.semantic);
      if (rect.width < 120 || rect.height < 55 || rect.width / rect.height < 1.05 ||
          rect.width / rect.height > 7 || (!hasResource && !namedBackground)) return null;
      let score = 0;
      if (hasResource) score += 5;
      if (namedBackground) score += 5;
      if (challengeWords.test(info.context)) score += 2;
      if (info.resource.naturalWidth && info.resource.naturalHeight) score += 2;
      if (rect.width >= 180 && rect.height >= 80) score += 2;
      return { info, score };
    }).filter(Boolean).sort((a, b) => b.score - a.score).slice(0, MAX_CANDIDATES_PER_STAGE);

    const pieceCandidates = nodes.map((info) => {
      const rect = info.rect;
      const namedPiece = pieceWords.test(info.semantic);
      const hasResource = info.resource.kind !== "none";
      const aspectRatio = rect.width / rect.height;
      const visualOverlay = info.resource.kind === "canvas" || info.resource.kind === "img";
      const tallNarrowVisual = visualOverlay && rect.height > 190 &&
        rect.width <= 190 && aspectRatio >= 0.1 && aspectRatio <= 0.5;
      const conventionalPieceShape = rect.height <= 190 &&
        aspectRatio >= 0.3 && aspectRatio <= 3.3;
      const resourceHint = typeof info.resource.url === "string" &&
          !info.resource.url.toLowerCase().startsWith("data:")
        ? info.resource.url.slice(0, 512)
        : "";
      const controlLike = pieceControlWords.test(`${info.semantic} ${resourceHint}`) ||
        (!namedPiece && iconWords.test(info.semantic) && interactive(info));
      if (rect.width < 14 || rect.height < 14 || rect.width > 190 ||
          (!conventionalPieceShape && !tallNarrowVisual) ||
          (!namedPiece && !hasResource) || controlLike) return null;
      let score = 0;
      if (namedPiece) score += 7;
      if (hasResource) score += 4;
      if (challengeWords.test(info.context)) score += 2;
      if (rect.width / rect.height >= 0.55 && rect.width / rect.height <= 1.8) score += 2;
      return {
        info,
        score,
        // A narrow canvas or image can be an otherwise anonymous full-height movable
        // overlay. It is admitted here only as a possibility; the pairing
        // stage below still requires it to be narrow and nearly exactly the
        // same rendered height as a plausible challenge background.
        fullHeightVisual: visualOverlay,
      };
    }).filter(Boolean).sort((a, b) => b.score - a.score).slice(0, MAX_CANDIDATES_PER_STAGE);

    const rawCandidates = [];
    for (const handleCandidate of handleCandidates) {
      const handle = handleCandidate.info;
      const handleAncestors = ancestors(handle.element, 8);
      for (let depth = 0; depth < handleAncestors.length; depth += 1) {
        const track = infoByElement.get(handleAncestors[depth]);
        if (!track) continue;
        const trackRect = track.rect;
        if (trackRect.width < Math.max(120, handle.rect.width * 2.2) ||
            trackRect.height < handle.rect.height * 0.65 ||
            trackRect.height > Math.max(150, handle.rect.height * 4) ||
            centerY(handle.rect) < trackRect.top - 8 || centerY(handle.rect) > bottom(trackRect) + 8 ||
            centerX(handle.rect) < trackRect.left - 12 || centerX(handle.rect) > right(trackRect) + 12) {
          continue;
        }
        let trackScore = 0;
        if (trackWords.test(track.semantic)) trackScore += 6;
        if (challengeWords.test(track.context)) trackScore += 3;
        if (depth <= 1) trackScore += 3;
        if (trackRect.width / handle.rect.width >= 4) trackScore += 2;
        if (centerX(handle.rect) <= trackRect.left + trackRect.width * 0.35) trackScore += 2;

        for (const backgroundCandidate of backgroundCandidates) {
          const background = backgroundCandidate.info;
          if (background.element === track.element || background.element === handle.element) continue;
          const horizontalRatio = horizontalOverlap(background.rect, trackRect) /
            Math.min(background.rect.width, trackRect.width);
          const verticalGap = trackRect.top - bottom(background.rect);
          if (horizontalRatio < 0.45 || verticalGap < -90 || verticalGap > 240) continue;
          let relationScore = 0;
          if (verticalGap >= -10 && verticalGap <= 100) relationScore += 6;
          else if (verticalGap >= -35 && verticalGap <= 150) relationScore += 3;
          if (horizontalRatio >= 0.8) relationScore += 4;
          else if (horizontalRatio >= 0.6) relationScore += 2;
          relationScore += Math.min(4,
            sharedAncestorStrength(background.element, track.element));

          for (const pieceCandidate of pieceCandidates) {
            const piece = pieceCandidate.info;
            if (piece.element === background.element || piece.element === track.element ||
                piece.element === handle.element) continue;
            const narrowFullHeightVisual = pieceCandidate.fullHeightVisual &&
              piece.rect.width <= background.rect.width * 0.35 &&
              piece.rect.height >= background.rect.height * 0.88 &&
              piece.rect.height <= background.rect.height * 1.05;
            if (piece.rect.width > background.rect.width * 0.58 ||
                (piece.rect.height > background.rect.height * 0.88 &&
                  !narrowFullHeightVisual)) continue;
            const yOverlapRatio = verticalOverlap(piece.rect, background.rect) /
              Math.min(piece.rect.height, background.rect.height);
            const horizontalDistance = Math.max(
              0,
              background.rect.left - right(piece.rect),
              piece.rect.left - right(background.rect),
            );
            if (yOverlapRatio < 0.35 || horizontalDistance > Math.max(30, piece.rect.width)) continue;
            let pieceRelationScore = 0;
            if (yOverlapRatio >= 0.8) pieceRelationScore += 5;
            else pieceRelationScore += 3;
            if (horizontalOverlap(piece.rect, background.rect) > 0) pieceRelationScore += 4;
            if (piece.rect.height >= background.rect.height * 0.18 &&
                piece.rect.height <= background.rect.height * 0.65) pieceRelationScore += 2;
            else if (narrowFullHeightVisual) pieceRelationScore += 3;
            pieceRelationScore += Math.min(3,
              sharedAncestorStrength(piece.element, background.element));

            rawCandidates.push({
              score: handleCandidate.score + trackScore + backgroundCandidate.score +
                relationScore + pieceCandidate.score + pieceRelationScore,
              handle,
              track,
              background,
              piece,
            });
          }
        }
      }
    }

    rawCandidates.sort((a, b) => b.score - a.score);
    const candidates = [];
    for (const candidate of rawCandidates) {
      const sameRegion = candidates.some((existing) =>
        existing.handle.element === candidate.handle.element ||
        existing.track.element === candidate.track.element ||
        (intersectionOverUnion(existing.track.rect, candidate.track.rect) >= 0.75 &&
          intersectionOverUnion(existing.background.rect, candidate.background.rect) >= 0.75));
      if (!sameRegion) candidates.push(candidate);
    }

    const best = candidates[0];
    if (!best || best.score < MIN_SCORE) {
      return errorResult("CHALLENGE_NOT_FOUND", "no supported visible slider challenge was found");
    }
    const second = candidates[1];
    if (second && second.score >= MIN_SCORE &&
        best.score - second.score <= Math.max(AMBIGUITY_SCORE_DELTA, best.score * 0.08)) {
      return errorResult("CHALLENGE_AMBIGUOUS", "multiple similar slider challenges were found");
    }

    const linkedOffsetMotion = (() => {
      const pieceOffsetLeft = Number(best.piece.element?.offsetLeft);
      const handleOffsetLeft = Number(best.handle.element?.offsetLeft);
      let pieceOffsetParent = null;
      let handleOffsetParent = null;
      try {
        pieceOffsetParent = best.piece.element?.offsetParent || null;
        handleOffsetParent = best.handle.element?.offsetParent || null;
      } catch {
        return null;
      }
      const background = best.background.rect;
      const piece = best.piece.rect;
      const track = best.track.rect;
      if (best.piece.resource.kind !== "img" ||
          !Number.isFinite(pieceOffsetLeft) || !Number.isFinite(handleOffsetLeft) ||
          pieceOffsetParent !== best.background.element ||
          handleOffsetParent !== best.track.element ||
          Math.abs(pieceOffsetLeft) > 2 || Math.abs(handleOffsetLeft) > 2 ||
          piece.width > background.width * 0.35 ||
          Math.abs(piece.top - background.top) > Math.max(1, background.height * 0.02) ||
          Math.abs(piece.height - background.height) > Math.max(1, background.height * 0.02) ||
          Math.abs(track.width - background.width) > Math.max(2, background.width * 0.02)) {
        return null;
      }
      return {
        kind: "linked-offset-left",
        initialHandleOffsetLeft: round(handleOffsetLeft),
        initialPieceOffsetLeft: round(pieceOffsetLeft),
      };
    })();

    const resourceDescriptor = (info) => ({
      rect: { ...info.rect },
      locator: locatorOf(info),
      semantic: info.semantic,
      resource: { ...info.resource },
    });
    const elementDescriptor = (info) => ({
      rect: { ...info.rect },
      locator: locatorOf(info),
      semantic: info.semantic,
    });
    const fingerprintParts = [
      "challenge-v1",
      best.handle.path.join("/"),
      best.track.path.join("/"),
      best.background.path.join("/"),
      best.piece.path.join("/"),
      best.background.resource.kind,
      best.background.resource.url || "",
      best.piece.resource.kind,
      best.piece.resource.url || "",
      best.background.resource.naturalWidth || 0,
      best.background.resource.naturalHeight || 0,
      best.piece.resource.naturalWidth || 0,
      best.piece.resource.naturalHeight || 0,
      linkedOffsetMotion?.kind || "scaled-ranges",
      linkedOffsetMotion?.initialHandleOffsetLeft || 0,
      linkedOffsetMotion?.initialPieceOffsetLeft || 0,
      ...[best.handle.rect, best.track.rect, best.background.rect, best.piece.rect]
        .flatMap((rect) => [rect.left, rect.top, rect.width, rect.height]
          .map((value) => Math.round(value * 2) / 2)),
    ];
    const fingerprintInput = fingerprintParts.join("|");
    let fingerprintHash = 2166136261;
    for (let index = 0; index < fingerprintInput.length; index += 1) {
      fingerprintHash ^= fingerprintInput.charCodeAt(index);
      fingerprintHash = Math.imul(fingerprintHash, 16777619);
    }

    return {
      ok: true,
      descriptor: {
        version: 1,
        score: round(best.score),
        handle: elementDescriptor(best.handle),
        track: elementDescriptor(best.track),
        background: resourceDescriptor(best.background),
        piece: resourceDescriptor(best.piece),
        motion: linkedOffsetMotion,
        viewport: {
          width: round(viewportWidth),
          height: round(viewportHeight),
          devicePixelRatio: Number.isFinite(Number(globalThis.devicePixelRatio)) &&
            Number(globalThis.devicePixelRatio) > 0 ? round(Number(globalThis.devicePixelRatio)) : 1,
          scrollX: Number.isFinite(Number(globalThis.scrollX)) ? round(Number(globalThis.scrollX)) : 0,
          scrollY: Number.isFinite(Number(globalThis.scrollY)) ? round(Number(globalThis.scrollY)) : 0,
        },
        fingerprint: `challenge-v1-${(fingerprintHash >>> 0).toString(16).padStart(8, "0")}`,
      },
    };
  } catch (error) {
    const message = typeof error?.message === "string"
      ? error.message.replace(/[\u0000-\u001f\u007f]/gu, " ").slice(0, 160)
      : "unexpected page scan failure";
    return errorResult("CHALLENGE_SCAN_FAILED", message || "unexpected page scan failure");
  }
}

export function setDetectedPieceVisibility(locator, visible) {
  const errorResult = (code, message) => ({
    ok: false,
    error: { code, message },
  });

  try {
    if (typeof visible !== "boolean" || locator === null || typeof locator !== "object" ||
        locator.version !== 1 || !Array.isArray(locator.path) || locator.path.length > 128) {
      return errorResult("ELEMENT_LOCATOR_INVALID", "element locator is invalid");
    }
    const documentObject = globalThis.document;
    if (!documentObject) {
      return errorResult("ELEMENT_VISIBILITY_UNAVAILABLE", "page document is unavailable");
    }
    let current = documentObject;
    for (const token of locator.path) {
      if (token === "shadow") {
        let shadowRoot = null;
        try {
          shadowRoot = current?.shadowRoot;
        } catch {
          shadowRoot = null;
        }
        if (!shadowRoot) {
          return errorResult("ELEMENT_NOT_FOUND", "element shadow root is no longer available");
        }
        current = shadowRoot;
      } else if (Number.isSafeInteger(token) && token >= 0) {
        let children;
        try {
          children = current?.children;
        } catch {
          children = null;
        }
        if (!children || token >= children.length) {
          return errorResult("ELEMENT_NOT_FOUND", "element locator no longer resolves");
        }
        current = children[token];
      } else {
        return errorResult("ELEMENT_LOCATOR_INVALID", "element locator path is invalid");
      }
    }
    if (!current?.style || typeof current.style.setProperty !== "function" ||
        typeof current.style.removeProperty !== "function") {
      return errorResult("ELEMENT_VISIBILITY_UNAVAILABLE", "element style is unavailable");
    }

    const stateKey = "__captchaSafeVisibilityStateV1__";
    if (!visible) {
      if (!Object.prototype.hasOwnProperty.call(current, stateKey)) {
        const value = typeof current.style.getPropertyValue === "function"
          ? current.style.getPropertyValue("visibility") : "";
        const priority = typeof current.style.getPropertyPriority === "function"
          ? current.style.getPropertyPriority("visibility") : "";
        Object.defineProperty(current, stateKey, {
          configurable: true,
          enumerable: false,
          writable: false,
          value: { value, priority },
        });
      }
      current.style.setProperty("visibility", "hidden", "important");
    } else if (Object.prototype.hasOwnProperty.call(current, stateKey)) {
      const state = current[stateKey];
      if (state.value) current.style.setProperty("visibility", state.value, state.priority || "");
      else current.style.removeProperty("visibility");
      delete current[stateKey];
    } else if (typeof current.style.getPropertyValue === "function" &&
        current.style.getPropertyValue("visibility") === "hidden" &&
        current.style.getPropertyPriority?.("visibility") === "important") {
      // executeScript normally reuses the frame's isolated world, so the
      // non-enumerable state above survives. If Chrome recreated that world,
      // fail safe by removing only the exact override this function writes.
      current.style.removeProperty("visibility");
    }

    const rawRect = current.getBoundingClientRect?.();
    const validRect = rawRect && [rawRect.left, rawRect.top, rawRect.width, rawRect.height]
      .every((value) => typeof value === "number" && Number.isFinite(value));
    return {
      ok: true,
      visible,
      locator: { version: 1, path: [...locator.path] },
      rect: validRect ? {
        left: Math.round(rawRect.left * 1000) / 1000,
        top: Math.round(rawRect.top * 1000) / 1000,
        width: Math.round(rawRect.width * 1000) / 1000,
        height: Math.round(rawRect.height * 1000) / 1000,
      } : null,
    };
  } catch (error) {
    const message = typeof error?.message === "string"
      ? error.message.replace(/[\u0000-\u001f\u007f]/gu, " ").slice(0, 160)
      : "element visibility update failed";
    return errorResult("ELEMENT_VISIBILITY_FAILED", message || "element visibility update failed");
  }
}
