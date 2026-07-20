import importlib.metadata
import importlib.util
import io
import unittest

from PIL import Image, ImageDraw

from calculate_distance import calculate_distance_from_bytes


DDDDOCR_AVAILABLE = importlib.util.find_spec("ddddocr") is not None


def patterned_png(width, height, *, background="white", pattern=False):
    image = Image.new("RGB", (width, height), background)
    if pattern:
        draw = ImageDraw.Draw(image)
        draw.rectangle((1, 1, width - 2, height - 2), outline="black", width=1)
        draw.line((1, 1, width - 2, height - 2), fill="black", width=1)
        draw.line((width - 2, 1, 1, height - 2), fill="black", width=1)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), image


@unittest.skipUnless(DDDDOCR_AVAILABLE, "ddddocr is not installed in the test interpreter")
class DdddOcrRuntimeContractTests(unittest.TestCase):
    def test_pinned_1_6_1_returns_center_and_confidence_schema(self):
        self.assertEqual(importlib.metadata.version("ddddocr"), "1.6.1")

        import ddddocr

        target_bytes, target_image = patterned_png(8, 8, pattern=True)
        background = Image.new("RGB", (32, 20), "white")
        background.paste(target_image, (13, 6))
        output = io.BytesIO()
        background.save(output, format="PNG")

        matcher = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        result = calculate_distance_from_bytes(
            target_bytes,
            output.getvalue(),
            ocr_factory=lambda: matcher,
            min_confidence=0.0,
        )

        self.assertEqual(len(result.target), 2)
        self.assertEqual(result.target, (result.target_x, result.target_y))
        self.assertEqual(result.target, (17, 10))
        self.assertGreaterEqual(result.confidence, 0.90)


if __name__ == "__main__":
    unittest.main()
