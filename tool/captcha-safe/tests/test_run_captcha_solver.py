import argparse
import contextlib
import stat
import unittest
from unittest import mock

from run_captcha_solver import (
    BrowserGeometry,
    ConfigurationError,
    GeometryError,
    VerificationError,
    _validate_public_config,
    _validate_verification_endpoint,
    image_target_center_to_pointer_distance,
    verify_with_backend,
    run,
    CapturedChallenge,
    _load_administrator_public_key,
    _HarnessRequestHandler,
    _validate_harness_url,
    validate_downloaded_images_against_browser,
    validate_vertical_match_alignment,
    _ClientTerminalSignal,
    _capture_challenge,
    _same_challenge_identity,
    UnsupportedChallengeError,
)


def geometry_mapping(**overrides):
    value = {
        "backgroundLeft": 100,
        "backgroundTop": 50,
        "backgroundWidth": 300,
        "backgroundHeight": 150,
        "backgroundNaturalWidth": 600,
        "backgroundNaturalHeight": 300,
        "puzzleLeft": 100,
        "puzzleTop": 50,
        "puzzleWidth": 50,
        "puzzleHeight": 50,
        "trackWidth": 300,
        "sliderWidth": 50,
        "devicePixelRatio": 2,
    }
    value.update(overrides)
    return value


class GeometryTests(unittest.TestCase):
    def test_converts_image_pixels_using_measured_travel_ranges(self):
        geometry = BrowserGeometry.from_mapping(geometry_mapping())
        self.assertEqual(image_target_center_to_pointer_distance(300, geometry), 125)

    def test_accounts_for_initial_puzzle_offset(self):
        geometry = BrowserGeometry.from_mapping(geometry_mapping(puzzleLeft=110))
        self.assertEqual(image_target_center_to_pointer_distance(300, geometry), 115)

    def test_rejects_invalid_geometry_and_target(self):
        with self.assertRaises(GeometryError):
            BrowserGeometry.from_mapping(geometry_mapping(trackWidth=0))
        with self.assertRaises(GeometryError):
            BrowserGeometry.from_mapping(geometry_mapping(backgroundNaturalWidth=600.5))
        with self.assertRaises(GeometryError):
            image_target_center_to_pointer_distance(
                -1, BrowserGeometry.from_mapping(geometry_mapping())
            )
        with self.assertRaises(GeometryError):
            image_target_center_to_pointer_distance(
                100,
                BrowserGeometry.from_mapping(geometry_mapping(backgroundHeight=100)),
            )

    def test_binds_downloaded_image_dimensions_to_browser_snapshot(self):
        from calculate_distance import DistanceResult, ImageInfo

        result = DistanceResult(
            target_x=300,
            target_y=100,
            target=(300, 100),
            confidence=0.9,
            target_image=ImageInfo(100, 100, "PNG", 100),
            background_image=ImageInfo(600, 300, "PNG", 1000),
        )
        geometry = BrowserGeometry.from_mapping(geometry_mapping())
        validate_downloaded_images_against_browser(result, geometry)
        with self.assertRaises(GeometryError):
            validate_downloaded_images_against_browser(
                result,
                BrowserGeometry.from_mapping(
                    geometry_mapping(backgroundNaturalWidth=1200)
                ),
            )
        with self.assertRaises(GeometryError):
            validate_downloaded_images_against_browser(
                result,
                BrowserGeometry.from_mapping(geometry_mapping(puzzleWidth=20)),
            )

        aligned = DistanceResult(
            target_x=300,
            target_y=50,
            target=(300, 50),
            confidence=0.9,
            target_image=result.target_image,
            background_image=result.background_image,
        )
        self.assertEqual(validate_vertical_match_alignment(aligned, geometry), 0.0)
        with self.assertRaises(GeometryError):
            validate_vertical_match_alignment(result, geometry)


class ConfigTests(unittest.TestCase):
    def test_public_config_is_narrowly_validated(self):
        from run_captcha_solver import SCENE_ID_PATTERN

        self.assertEqual(
            _validate_public_config("scene_123-ABC", "scene", SCENE_ID_PATTERN),
            "scene_123-ABC",
        )
        for value in (None, "", "space here", "x" * 129, "<script>"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                _validate_public_config(value, "scene", SCENE_ID_PATTERN)

    def test_verification_endpoint_is_https_or_loopback(self):
        for endpoint in (
            "https://verify.example/api/captcha",
            "http://127.0.0.1:8080/verify",
            "http://localhost/verify",
        ):
            _validate_verification_endpoint(endpoint)
        for endpoint in (
            "http://verify.example/api",
            "https://user:pass@verify.example/api",
            "ftp://verify.example/api",
            "https://verify.example/api#fragment",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ConfigurationError):
                _validate_verification_endpoint(endpoint)

    def test_harness_url_requires_reviewed_filename_and_safe_origin(self):
        self.assertEqual(
            _validate_harness_url(
                "https://test.example/captcha/ai_studio_code%20%281%29.html",
                allow_loopback=False,
            ),
            "https://test.example/captcha/ai_studio_code%20%281%29.html",
        )
        self.assertEqual(
            _validate_harness_url(
                "http://127.0.0.1:8080/ai_studio_code%20%281%29.html",
                allow_loopback=True,
            ),
            "http://127.0.0.1:8080/ai_studio_code%20%281%29.html",
        )
        for value in (
            "http://test.example/ai_studio_code%20%281%29.html",
            "https://test.example/other.html",
            "https://user:pass@test.example/ai_studio_code%20%281%29.html",
            "https://test.example/../ai_studio_code%20%281%29.html",
            "https://test.example/ai_studio_code%20%281%29.html?scene=x",
        ):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                _validate_harness_url(value, allow_loopback=False)

    def test_harness_server_exposes_only_reviewed_assets(self):
        for target in (
            "/ai_studio_code%20%281%29.html?sceneId=x",
            "/harness.js",
            "/harness.css",
        ):
            self.assertTrue(_HarnessRequestHandler.is_allowed_target(target))
        for target in (
            "/",
            "/README.md",
            "/license_manager.py",
            "/tests/test_license_manager.py",
            "/..%2FREADME.md",
            "//host/harness.js",
        ):
            self.assertFalse(_HarnessRequestHandler.is_allowed_target(target))

    def test_local_harness_csp_allows_both_official_script_origins(self):
        handler = object.__new__(_HarnessRequestHandler)
        headers = {}
        handler.send_header = lambda name, value: headers.__setitem__(name, value)
        with mock.patch("http.server.SimpleHTTPRequestHandler.end_headers"):
            handler.end_headers()
        csp = headers["Content-Security-Policy"]
        self.assertIn(
            "script-src 'self' https://o.alicdn.com https://g.alicdn.com",
            csp,
        )


class SnapshotDriver:
    def __init__(self, snapshots, *, state="CHALLENGE_OPEN"):
        self.snapshots = list(snapshots)
        self.last_snapshot = self.snapshots[-1] if self.snapshots else None
        self.state = state

    def execute_script(self, script, *args):
        if "function observation" in script:
            if self.snapshots:
                self.last_snapshot = self.snapshots.pop(0)
            return {
                "harnessState": {"attemptId": "attempt-1", "status": self.state},
                "challenge": self.last_snapshot,
            }
        if "__captchaHarness" in script:
            return {"attemptId": "attempt-1", "status": self.state}
        return None


class ChallengeCaptureTests(unittest.TestCase):
    def snapshot(self, *, background_url="https://static-captcha.aliyuncs.com/bg.png"):
        return {
            "shadowUrl": "https://static-captcha.aliyuncs.com/target.png",
            "backgroundUrl": background_url,
            "sliderElement": object(),
            "geometry": geometry_mapping(),
        }

    def test_requires_two_stable_atomic_snapshots(self):
        old = self.snapshot(background_url="https://static-captcha.aliyuncs.com/old.png")
        new = self.snapshot(background_url="https://static-captcha.aliyuncs.com/new.png")
        challenge = _capture_challenge(
            SnapshotDriver([old, new, new]),
            timeout=0.5,
            attempt_id="attempt-1",
        )
        self.assertEqual(challenge.background_url, new["backgroundUrl"])
        self.assertTrue(_same_challenge_identity(challenge, challenge))
        self.assertFalse(
            _same_challenge_identity(
                challenge,
                CapturedChallenge(
                    shadow_url=challenge.shadow_url,
                    background_url=old["backgroundUrl"],
                    geometry=challenge.geometry,
                ),
            )
        )

    def test_surfaces_terminal_or_unsupported_challenge(self):
        with self.assertRaises(_ClientTerminalSignal):
            _capture_challenge(
                SnapshotDriver(
                    [self.snapshot(), self.snapshot()],
                    state="CLIENT_PASS",
                ),
                timeout=0.2,
                attempt_id="attempt-1",
            )
        with self.assertRaises(UnsupportedChallengeError):
            _capture_challenge(
                SnapshotDriver([]),
                timeout=0.12,
                attempt_id="attempt-1",
            )


class FakeResponse:
    def __init__(self, payload, *, status=200, content_type="application/json"):
        self.payload = payload
        self.status_code = status
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=16384):
        import json

        if isinstance(self.payload, Exception):
            body = b"not-json"
        else:
            body = json.dumps(self.payload).encode("utf-8")
        for offset in range(0, len(body), chunk_size):
            yield body[offset : offset + chunk_size]


class OversizedResponse(FakeResponse):
    def iter_content(self, chunk_size=16384):
        yield b"x" * (64 * 1024 + 1)


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return self.response


class BackendVerificationTests(unittest.TestCase):
    def verify(self, response):
        session = FakeSession(response)
        result = verify_with_backend(
            "https://verify.example/captcha",
            captcha_verify_param="opaque-client-proof",
            scene_id="scene-1",
            region="cn",
            user_certify_id="prefix01_Ab3dE5fG7h",
            attempt_id="attempt-1",
            session=session,
        )
        return result, session

    def test_accepts_only_explicit_backend_verdict(self):
        result, session = self.verify(
            FakeResponse(
                {
                    "verified": True,
                    "attemptId": "attempt-1",
                    "userCertifyId": "prefix01_Ab3dE5fG7h",
                }
            )
        )
        self.assertTrue(result)
        _, kwargs = session.calls[0]
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["json"]["captchaVerifyParam"], "opaque-client-proof")
        self.assertEqual(kwargs["json"]["region"], "cn")
        self.assertEqual(kwargs["json"]["userCertifyId"], "prefix01_Ab3dE5fG7h")

        result, _ = self.verify(
            FakeResponse(
                {
                    "verified": False,
                    "attemptId": "attempt-1",
                    "userCertifyId": "prefix01_Ab3dE5fG7h",
                }
            )
        )
        self.assertFalse(result)

    def test_rejects_redirect_non_json_and_mismatched_attempt(self):
        responses = (
            FakeResponse({}, status=302),
            FakeResponse({}, content_type="text/html"),
            FakeResponse(
                {
                    "verified": True,
                    "attemptId": "different",
                    "userCertifyId": "prefix01_Ab3dE5fG7h",
                }
            ),
            FakeResponse({"verified": "yes"}),
            FakeResponse(
                {
                    "verified": True,
                    "attemptId": "attempt-1",
                    "userCertifyId": "different",
                }
            ),
            FakeResponse({"verified": True, "attemptId": "attempt-1"}),
        )
        for response in responses:
            with self.subTest(status=response.status_code, payload=response.payload):
                with self.assertRaises(VerificationError):
                    self.verify(response)

    def test_rejects_missing_or_oversized_client_proof(self):
        for proof in ("", "x" * 64_001):
            with self.subTest(size=len(proof)), self.assertRaises(VerificationError):
                verify_with_backend(
                    "https://verify.example/captcha",
                    captcha_verify_param=proof,
                    scene_id="scene-1",
                    region="cn",
                    user_certify_id="prefix01_Ab3dE5fG7h",
                    attempt_id="attempt-1",
                    session=FakeSession(FakeResponse({"verified": True})),
                )

    def test_rejects_oversized_backend_response(self):
        with self.assertRaises(VerificationError):
            self.verify(OversizedResponse({"verified": True}))


class FakeDriver:
    def __init__(self, *, get_error=None, token="opaque-token"):
        self.get_error = get_error
        self.token = token
        self.urls = []
        self.quit_calls = 0

    def get(self, url):
        self.urls.append(url)
        if self.get_error:
            raise self.get_error

    def execute_script(self, script, *args):
        if "consumeClientToken" in script:
            return self.token
        return None

    def quit(self):
        self.quit_calls += 1


class RunnerLifecycleTests(unittest.TestCase):
    def args(self, **overrides):
        values = {
            "scene_id": "scene_1234",
            "prefix": "prefix01",
            "region": "cn",
            "language": "cn",
            "harness_url": None,
            "allow_loopback_harness": True,
            "allowed_host": None,
            "max_image_bytes": 8 * 1024 * 1024,
            "min_confidence": 0.50,
            "timeout": 1.0,
            "headless": True,
            "execute_drag": False,
            "license_file": "/does/not/matter.json",
            "public_key": None,
            "verification_endpoint": None,
            "pretty": False,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def challenge(self, **geometry_overrides):
        return CapturedChallenge(
            shadow_url="https://static-captcha.aliyuncs.com/target.png",
            background_url="https://static-captcha.aliyuncs.com/background.png",
            geometry=BrowserGeometry.from_mapping(
                geometry_mapping(**geometry_overrides)
            ),
        )

    def distance_result(self):
        from calculate_distance import DistanceResult, ImageInfo

        return DistanceResult(
            target_x=300,
            target_y=50,
            target=(300, 50),
            confidence=0.93,
            target_image=ImageInfo(100, 100, "PNG", 100),
            background_image=ImageInfo(600, 300, "PNG", 1000),
        )

    def test_driver_is_always_closed_after_navigation_failure(self):
        driver = FakeDriver(get_error=RuntimeError("navigation failed"))
        with mock.patch("run_captcha_solver._require_authorization"), mock.patch(
            "run_captcha_solver._create_driver", return_value=driver
        ), mock.patch(
            "run_captcha_solver.serve_harness",
            return_value=contextlib.nullcontext("http://127.0.0.1:9999"),
        ):
            code, report = run(self.args())
        self.assertEqual(code, 10)
        self.assertEqual(report.status, "UNEXPECTED_ERROR")
        self.assertEqual(driver.quit_calls, 1)

    def test_dry_run_stops_after_validated_distance(self):
        driver = FakeDriver()
        state = {"attemptId": None, "status": "READY"}

        def harness_state(_driver):
            # run creates the UUID internally; reflect it from the current report
            # by extracting the query passed to the fake browser.
            from urllib.parse import parse_qs, urlsplit

            state["attemptId"] = parse_qs(urlsplit(driver.urls[-1]).query)["attemptId"][0]
            return state

        with (
            mock.patch("run_captcha_solver._require_authorization"),
            mock.patch(
                "run_captcha_solver.serve_harness",
                return_value=contextlib.nullcontext("http://127.0.0.1:9999"),
            ),
            mock.patch("run_captcha_solver._create_driver", return_value=driver),
            mock.patch("run_captcha_solver._read_harness_state", side_effect=harness_state),
            mock.patch("run_captcha_solver._click_trigger"),
            mock.patch("run_captcha_solver._capture_challenge", return_value=self.challenge()),
            mock.patch(
                "run_captcha_solver.calculate_distance_from_urls",
                return_value=self.distance_result(),
            ),
            mock.patch("run_captcha_solver._perform_pointer_drag") as drag,
        ):
            code, report = run(self.args())

        self.assertEqual(code, 0)
        self.assertEqual(report.status, "DISTANCE_READY")
        self.assertEqual(report.image_target_center_x, 300)
        self.assertEqual(report.image_target_center_y, 50)
        self.assertEqual(report.vertical_alignment_error, 0.0)
        self.assertRegex(report.user_certify_id, r"^prefix01_[A-Za-z0-9]{10}$")
        self.assertAlmostEqual(report.match_confidence, 0.93)
        self.assertEqual(report.pointer_distance, 125)
        drag.assert_not_called()
        self.assertEqual(driver.quit_calls, 1)
        self.assertIn("ai_studio_code%20%281%29.html", driver.urls[0])

    def test_execute_without_backend_fails_before_browser_launch(self):
        with mock.patch("run_captcha_solver._create_driver") as create_driver, mock.patch(
            "run_captcha_solver._require_authorization"
        ) as authorize:
            code, report = run(self.args(execute_drag=True, public_key="/key.pem"))

        self.assertEqual(code, 2)
        self.assertEqual(report.status, "CONFIGURATION_ERROR")
        self.assertIn("verification-endpoint", report.error)
        authorize.assert_not_called()
        create_driver.assert_not_called()

    def test_requires_explicit_harness_origin_choice(self):
        with mock.patch("run_captcha_solver._require_authorization") as authorize:
            code, report = run(self.args(allow_loopback_harness=False))
        self.assertEqual(code, 2)
        self.assertEqual(report.status, "CONFIGURATION_ERROR")
        self.assertIn("harness", report.error)
        authorize.assert_not_called()

    def test_sgp_default_host_and_harness_origin_are_licensed(self):
        driver = FakeDriver(get_error=RuntimeError("stop after navigation"))
        with mock.patch("run_captcha_solver._require_authorization") as authorize, mock.patch(
            "run_captcha_solver._create_driver", return_value=driver
        ), mock.patch(
            "run_captcha_solver.serve_harness",
            return_value=contextlib.nullcontext("http://127.0.0.1:9999"),
        ):
            code, _ = run(self.args(region="sgp"))

        self.assertEqual(code, 10)
        licensed_hosts = authorize.call_args.args[1]
        self.assertIn("static-captcha-sgp.aliyuncs.com", licensed_hosts)
        self.assertIn("127.0.0.1", licensed_hosts)
        self.assertNotIn("static-captcha.aliyuncs.com", licensed_hosts)

    def test_verification_backend_is_in_license_scope(self):
        driver = FakeDriver(get_error=RuntimeError("stop after navigation"))
        with mock.patch("run_captcha_solver._require_authorization") as authorize, mock.patch(
            "run_captcha_solver._create_driver", return_value=driver
        ), mock.patch(
            "run_captcha_solver.serve_harness",
            return_value=contextlib.nullcontext("http://127.0.0.1:9999"),
        ):
            code, _ = run(
                self.args(
                    execute_drag=True,
                    verification_endpoint="https://verification-backend.example/verify",
                )
            )

        self.assertEqual(code, 10)
        licensed_hosts = authorize.call_args.args[1]
        self.assertIn("verification-backend.example", licensed_hosts)

    def test_no_jigsaw_client_pass_is_not_reported_as_server_verified(self):
        driver = FakeDriver()

        def harness_state(_driver):
            from urllib.parse import parse_qs, urlsplit

            return {
                "attemptId": parse_qs(urlsplit(driver.urls[-1]).query)["attemptId"][0],
                "status": "READY",
            }

        def terminal(_driver, _timeout, attempt_id):
            raise _ClientTerminalSignal(
                {"attemptId": attempt_id, "status": "CLIENT_PASS", "error": None}
            )

        with (
            mock.patch("run_captcha_solver._require_authorization"),
            mock.patch(
                "run_captcha_solver.serve_harness",
                return_value=contextlib.nullcontext("http://127.0.0.1:9999"),
            ),
            mock.patch("run_captcha_solver._create_driver", return_value=driver),
            mock.patch("run_captcha_solver._read_harness_state", side_effect=harness_state),
            mock.patch("run_captcha_solver._click_trigger"),
            mock.patch("run_captcha_solver._capture_challenge", side_effect=terminal),
        ):
            code, report = run(self.args())

        self.assertEqual(code, 0)
        self.assertEqual(report.status, "NO_JIGSAW_CLIENT_PASS")
        self.assertEqual(report.client_status, "CLIENT_PASS")
        self.assertIsNone(report.server_verified)
        self.assertIsNone(report.pointer_distance)
        self.assertEqual(driver.quit_calls, 1)

    def test_execute_drag_happy_path_requires_backend_verified(self):
        driver = FakeDriver(token="opaque-token")
        phase = {"dragged": False}

        def harness_state(_driver):
            from urllib.parse import parse_qs, urlsplit

            return {
                "attemptId": parse_qs(urlsplit(driver.urls[-1]).query)["attemptId"][0],
                "status": "CLIENT_PASS" if phase["dragged"] else "READY",
                "error": None,
            }

        def mark_dragged(*args, **kwargs):
            phase["dragged"] = True

        with (
            mock.patch("run_captcha_solver._require_authorization"),
            mock.patch(
                "run_captcha_solver.serve_harness",
                return_value=contextlib.nullcontext("http://127.0.0.1:9999"),
            ),
            mock.patch("run_captcha_solver._create_driver", return_value=driver),
            mock.patch("run_captcha_solver._read_harness_state", side_effect=harness_state),
            mock.patch("run_captcha_solver._click_trigger"),
            mock.patch(
                "run_captcha_solver._capture_challenge",
                side_effect=[self.challenge(), self.challenge()],
            ),
            mock.patch(
                "run_captcha_solver.calculate_distance_from_urls",
                return_value=self.distance_result(),
            ),
            mock.patch(
                "run_captcha_solver._perform_pointer_drag",
                side_effect=mark_dragged,
            ) as drag,
            mock.patch(
                "run_captcha_solver.verify_with_backend",
                return_value=True,
            ) as verify,
        ):
            code, report = run(
                self.args(
                    execute_drag=True,
                    verification_endpoint="https://verification-backend.example/verify",
                )
            )

        self.assertEqual(code, 0)
        self.assertEqual(report.status, "SERVER_VERIFIED")
        self.assertTrue(report.server_verified)
        drag.assert_called_once()
        self.assertEqual(verify.call_args.kwargs["captcha_verify_param"], "opaque-token")
        self.assertEqual(
            verify.call_args.kwargs["user_certify_id"],
            report.user_certify_id,
        )
        self.assertEqual(driver.quit_calls, 1)

    def test_fresh_vertical_mismatch_blocks_drag(self):
        driver = FakeDriver()

        def harness_state(_driver):
            from urllib.parse import parse_qs, urlsplit

            return {
                "attemptId": parse_qs(urlsplit(driver.urls[-1]).query)["attemptId"][0],
                "status": "READY",
            }

        with (
            mock.patch("run_captcha_solver._require_authorization"),
            mock.patch(
                "run_captcha_solver.serve_harness",
                return_value=contextlib.nullcontext("http://127.0.0.1:9999"),
            ),
            mock.patch("run_captcha_solver._create_driver", return_value=driver),
            mock.patch("run_captcha_solver._read_harness_state", side_effect=harness_state),
            mock.patch("run_captcha_solver._click_trigger"),
            mock.patch(
                "run_captcha_solver._capture_challenge",
                side_effect=[self.challenge(), self.challenge(puzzleTop=80)],
            ),
            mock.patch(
                "run_captcha_solver.calculate_distance_from_urls",
                return_value=self.distance_result(),
            ),
            mock.patch("run_captcha_solver._perform_pointer_drag") as drag,
        ):
            code, report = run(
                self.args(
                    execute_drag=True,
                    verification_endpoint="https://verification-backend.example/verify",
                )
            )

        self.assertEqual(code, 3)
        self.assertEqual(report.status, "BROWSER_ERROR")
        self.assertIn("row", report.error)
        drag.assert_not_called()
        self.assertEqual(driver.quit_calls, 1)


class TrustAnchorTests(unittest.TestCase):
    def test_rejects_missing_relative_and_non_administrator_key(self):
        for value in (None, "relative.pem"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                _load_administrator_public_key(value)

        fake_info = mock.Mock(st_mode=stat.S_IFREG | 0o644, st_uid=501)
        fake_handle = mock.MagicMock()
        fake_handle.fileno.return_value = 10
        with mock.patch("run_captcha_solver.os.open", return_value=10), mock.patch(
            "run_captcha_solver.os.fdopen", return_value=fake_handle
        ), mock.patch("run_captcha_solver.os.fstat", return_value=fake_info):
            with self.assertRaises(ConfigurationError):
                _load_administrator_public_key("/tmp/operator-key.pem")


if __name__ == "__main__":
    unittest.main()
