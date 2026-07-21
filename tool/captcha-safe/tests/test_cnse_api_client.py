import base64
import io
import json
import unittest

from PIL import Image

from cnse_api_client import (
    CAPTCHA_PATH,
    SEARCH_PATH,
    CnseApiClient,
    CnseConfigurationError,
    CnseProtocolError,
    CnseRecognitionError,
    CnseRequestError,
)
from cnse_opencv_solver import OpenCvMatch


def png_bytes(width, height, *, offset=0):
    output = io.BytesIO()
    image = Image.new("RGB", (width, height), (240, 240, 240))
    image.putpixel((offset % width, offset % height), (0, 0, 0))
    image.save(output, format="PNG")
    return output.getvalue()


def challenge_json(*, y_height=51):
    return {
        "errcode": 0,
        "errmsg": "success",
        "yHeight": y_height,
        "smallImage": base64.b64encode(png_bytes(55, 45, offset=1)).decode(),
        "bigImage": base64.b64encode(png_bytes(500, 281, offset=2)).decode(),
    }


ROW = {
    "dwid": "46c6accf-684e-4d0c-bb49-a42f72fa9f1f",
    "fzjg": "新疆维吾尔自治区阿克苏地区市场监督管理局",
    "zsyxq": "2029-01-25",
    "dwmc": "新疆智仁能源有限公司拜城县察尔齐加气站",
    "dwlb": "特种设备气体充装单位",
    "sjgxsj": "2026-07-20",
    "zsyxqyz": "",
}


class FakeResponse:
    def __init__(self, value, *, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def fake_solver(_puzzle, _background, *, min_confidence=0.5):
    return OpenCvMatch(
        confidence=0.91,
        left=178,
        top=51,
        width=55,
        height=45,
        background_width=500,
        background_height=281,
        strategy="masked-photometric",
    )


class CnseApiClientTests(unittest.TestCase):
    def client(self, responses, **kwargs):
        session = FakeSession(responses)
        return CnseApiClient(
            session=session,
            solver=fake_solver,
            **kwargs,
        ), session

    def test_query_uses_one_session_and_matches_extension_contract(self):
        responses = [
            FakeResponse(challenge_json()),
            FakeResponse({"total": 1, "rows": [ROW]}),
        ]
        client, session = self.client(responses)

        result = client.query("新疆 智仁能源有限公司拜城县察尔齐加气站")

        self.assertEqual(result.keyword, ROW["dwmc"])
        self.assertEqual(result.move_length, 177)
        self.assertEqual(result.api_y_height, 51)
        self.assertEqual(result.match_box, {"x": 178, "y": 51, "width": 55, "height": 45})
        self.assertEqual(result.total, 1)
        self.assertEqual(result.rows, (ROW,))
        self.assertEqual([call[0] for call in session.calls], ["GET", "POST"])
        self.assertTrue(session.calls[0][1].endswith(CAPTCHA_PATH))
        self.assertTrue(session.calls[1][1].endswith(SEARCH_PATH))
        self.assertEqual(session.calls[1][2]["data"], {
            "keyword": ROW["dwmc"],
            "moveLength": "177",
            "pageNumber": "1",
            "pageSize": "10",
        })
        for _, _, options in session.calls:
            self.assertFalse(options["allow_redirects"])
            self.assertTrue(options["stream"])
            self.assertEqual(options["headers"]["X-Requested-With"], "XMLHttpRequest")

    def test_result_serializes_the_public_api_shape(self):
        client, _ = self.client([
            FakeResponse(challenge_json()),
            FakeResponse({"total": 1, "rows": [ROW]}),
        ])
        value = client.query(ROW["dwmc"]).to_dict()
        self.assertEqual(value["status"], "COMPLETED")
        self.assertEqual(value["captureMode"], "api")
        self.assertEqual(value["queryEndpoint"], SEARCH_PATH)
        self.assertEqual(value["rows"], [ROW])
        self.assertEqual(value["moveLength"], 177)
        self.assertEqual(value["apiYHeight"], 51)
        self.assertNotIn("move_length", value)

    def test_rejects_unapproved_origins_and_invalid_keywords(self):
        for origin in (
            "http://cnse.samr.gov.cn",
            "https://evil.example",
            "https://user:pass@cnse.samr.gov.cn",
            "https://cnse.samr.gov.cn/path",
        ):
            with self.subTest(origin=origin), self.assertRaises(CnseConfigurationError):
                CnseApiClient(origin=origin, session=FakeSession([]))
        for keyword in ("", " " * 5, "x" * 513):
            with self.subTest(keyword=keyword), self.assertRaises(CnseConfigurationError):
                CnseApiClient(session=FakeSession([])).query(keyword)

    def test_rejects_malformed_challenge_and_query_rows(self):
        invalid_challenge = challenge_json()
        invalid_challenge["extra"] = True
        client, _ = self.client([FakeResponse(invalid_challenge)])
        with self.assertRaises(CnseProtocolError):
            client.fetch_challenge()

        invalid_row = dict(ROW)
        invalid_row.pop("dwid")
        client, _ = self.client([
            FakeResponse(challenge_json()),
            FakeResponse({"total": 1, "rows": [invalid_row]}),
        ])
        with self.assertRaises(CnseProtocolError):
            client.query(ROW["dwmc"])

    def test_rejects_vertical_mismatch_before_submission(self):
        session = FakeSession([FakeResponse(challenge_json(y_height=10))])
        client = CnseApiClient(session=session, solver=fake_solver)
        with self.assertRaises(CnseRecognitionError):
            client.query(ROW["dwmc"])
        self.assertEqual(len(session.calls), 1)

    def test_rejects_redirect_and_oversized_declared_response(self):
        for response in (
            FakeResponse({}, status=302),
            FakeResponse({}, headers={"Content-Length": str(20 * 1024 * 1024)}),
        ):
            with self.subTest(status=response.status_code):
                client, _ = self.client([response])
                with self.assertRaises(CnseRequestError):
                    client.fetch_challenge()


if __name__ == "__main__":
    unittest.main()
