import io
import unittest

from PIL import Image

from calculate_distance import (
    DownloadError,
    DownloadPolicy,
    ImageValidationError,
    PolicyError,
    SolverError,
    _download_image,
    calculate_distance_from_bytes,
    calculate_distance_from_urls,
)


def png_bytes(width: int, height: int) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    image.putpixel((0, 0), (0, 0, 0, 255))
    image.save(output, format="PNG")
    return output.getvalue()


class FakeResponse:
    def __init__(self, body=b"", *, status=200, content_type="image/png", headers=None):
        self.body = body
        self.status_code = status
        self.headers = {"Content-Type": content_type, **(headers or {})}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class FakeMatcher:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def slide_match(self, target, background):
        self.calls.append((target, background))
        return self.result


class DownloadPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = DownloadPolicy(allowed_hosts=("static-captcha.aliyuncs.com",))

    def test_accepts_only_explicitly_approved_hosts(self):
        self.assertEqual(
            self.policy.validate_url("https://static-captcha.aliyuncs.com/a.png").hostname,
            "static-captcha.aliyuncs.com",
        )
        with self.assertRaises(PolicyError):
            self.policy.validate_url("https://edge.static-captcha.aliyuncs.com/a.png")

    def test_rejects_unapproved_or_unsafe_urls(self):
        rejected = (
            "http://static-captcha.aliyuncs.com/a.png",
            "https://evil.example/a.png",
            "https://notstatic-captcha.aliyuncs.com/a.png",
            "https://user:pass@static-captcha.aliyuncs.com/a.png",
            "https://127.0.0.1/a.png",
            "https://static-captcha.aliyuncs.com:444/a.png",
            "https://static-captcha.aliyuncs.com/a.png#fragment",
            "https://static-captcha.aliyuncs.com/a.png\nignored",
            "https://[bad/a.png",
            "https://static-captcha.aliyuncs.com：443/a.png",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(PolicyError):
                self.policy.validate_url(value)

    def test_rejects_invalid_limits(self):
        for kwargs in (
            {"max_bytes": 0},
            {"max_bytes": True},
            {"max_pixels": 1.5},
            {"connect_timeout": 0},
            {"read_timeout": float("inf")},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(PolicyError):
                DownloadPolicy(**kwargs)
        for host in ("com", "localhost", "127.0.0.1", "*.aliyuncs.com", "bad host"):
            with self.subTest(host=host), self.assertRaises(PolicyError):
                DownloadPolicy(allowed_hosts=(host,))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://static-captcha.aliyuncs.com/a.png"

    def test_download_is_streamed_without_redirects(self):
        body = png_bytes(10, 5)
        session = FakeSession([FakeResponse(body, headers={"Content-Length": str(len(body))})])
        downloaded, info = _download_image(self.url, DownloadPolicy(), session=session)
        self.assertEqual(downloaded, body)
        self.assertEqual((info.width, info.height, info.format), (10, 5, "PNG"))
        _, kwargs = session.calls[0]
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["stream"])

    def test_rejects_redirect_non_image_and_oversized_stream(self):
        cases = (
            (FakeResponse(status=302), DownloadError),
            (FakeResponse(b"not an image", content_type="text/html"), DownloadError),
            (FakeResponse(b"x" * 17), DownloadError),
        )
        for response, expected in cases:
            with self.subTest(status=response.status_code, content_type=response.headers["Content-Type"]):
                with self.assertRaises(expected):
                    _download_image(
                        self.url,
                        DownloadPolicy(max_bytes=16),
                        session=FakeSession([response]),
                    )

    def test_rejects_invalid_image_bytes(self):
        with self.assertRaises(ImageValidationError):
            _download_image(
                self.url,
                DownloadPolicy(),
                session=FakeSession([FakeResponse(b"not-png")]),
            )


class DistanceCalculationTests(unittest.TestCase):
    def test_rejects_uniform_or_oversized_inputs_before_ocr(self):
        uniform = io.BytesIO()
        Image.new("RGB", (4, 4), "black").save(uniform, format="PNG")
        matcher = FakeMatcher(
            {"target": [2, 2], "target_x": 2, "target_y": 2, "confidence": 1.0}
        )
        with self.assertRaises(SolverError):
            calculate_distance_from_bytes(
                uniform.getvalue(),
                png_bytes(10, 10),
                ocr_factory=lambda: matcher,
            )
        self.assertEqual(matcher.calls, [])

        alpha_only = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        alpha_only.putpixel((0, 0), (0, 0, 0, 255))
        alpha_output = io.BytesIO()
        alpha_only.save(alpha_output, format="PNG")
        with self.assertRaises(SolverError):
            calculate_distance_from_bytes(
                alpha_output.getvalue(),
                png_bytes(10, 10),
                ocr_factory=lambda: matcher,
            )
        self.assertEqual(matcher.calls, [])

        with self.assertRaises(SolverError):
            calculate_distance_from_bytes(
                png_bytes(12, 12),
                png_bytes(10, 10),
                ocr_factory=lambda: matcher,
            )
        self.assertEqual(matcher.calls, [])

    def test_url_path_applies_the_same_degenerate_input_guards(self):
        uniform = io.BytesIO()
        Image.new("RGB", (4, 4), "black").save(uniform, format="PNG")
        matcher = FakeMatcher(
            {"target": [2, 2], "target_x": 2, "target_y": 2, "confidence": 1.0}
        )
        with self.assertRaises(SolverError):
            calculate_distance_from_urls(
                "https://static-captcha.aliyuncs.com/target.png",
                "https://static-captcha.aliyuncs.com/background.png",
                session=FakeSession(
                    [FakeResponse(uniform.getvalue()), FakeResponse(png_bytes(10, 10))]
                ),
                ocr_factory=lambda: matcher,
            )
        self.assertEqual(matcher.calls, [])

    def test_validates_match_and_preserves_image_coordinates(self):
        target = png_bytes(2, 2)
        background = png_bytes(10, 5)
        matcher = FakeMatcher(
            {"target": [3, 1], "target_x": 3, "target_y": 1, "confidence": 0.91}
        )

        result = calculate_distance_from_bytes(
            target,
            background,
            ocr_factory=lambda: matcher,
        )

        self.assertEqual(result.match_center_x, 3)
        self.assertEqual(result.target, (3, 1))
        self.assertAlmostEqual(result.confidence, 0.91)
        self.assertEqual(matcher.calls, [(target, background)])

    def test_rejects_malformed_or_out_of_bounds_match(self):
        target = png_bytes(2, 2)
        background = png_bytes(10, 5)
        invalid_results = (
            None,
            {},
            {"target": [3, 1, 5, 3], "target_x": 3, "target_y": 1, "confidence": 0.9},
            {"target": [20, 1], "target_x": 20, "target_y": 1, "confidence": 0.9},
            {"target": [3, 1], "target_x": 4, "target_y": 1, "confidence": 0.9},
            {"target": [3.5, 1], "target_x": 3.5, "target_y": 1, "confidence": 0.9},
            {"target": [3, 1], "target_x": 3, "target_y": 1, "confidence": 0.1},
        )
        for raw in invalid_results:
            with self.subTest(raw=raw), self.assertRaises(SolverError):
                calculate_distance_from_bytes(
                    target,
                    background,
                    ocr_factory=lambda raw=raw: FakeMatcher(raw),
                )

    def test_odd_sized_target_accepts_both_legal_edges(self):
        target = png_bytes(3, 3)
        background = png_bytes(10, 7)
        for center in ((1, 1), (8, 5)):
            with self.subTest(center=center):
                result = calculate_distance_from_bytes(
                    target,
                    background,
                    ocr_factory=lambda center=center: FakeMatcher(
                        {
                            "target": list(center),
                            "target_x": center[0],
                            "target_y": center[1],
                            "confidence": 0.9,
                        }
                    ),
                )
                self.assertEqual(result.target, center)

    def test_url_pair_uses_one_explicit_session(self):
        target = png_bytes(2, 2)
        background = png_bytes(10, 5)
        session = FakeSession([FakeResponse(target), FakeResponse(background)])
        result = calculate_distance_from_urls(
            "https://static-captcha.aliyuncs.com/target.png",
            "https://static-captcha.aliyuncs.com/background.png",
            session=session,
            ocr_factory=lambda: FakeMatcher(
                {"target": [4, 2], "target_x": 4, "target_y": 2, "confidence": 0.88}
            ),
        )
        self.assertEqual(result.match_center_x, 4)
        self.assertEqual(len(session.calls), 2)


if __name__ == "__main__":
    unittest.main()
