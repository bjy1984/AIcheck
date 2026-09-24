"""Protocol tests for local-only inputs and stateless review services; no real accounts."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

SPEC = importlib.util.spec_from_file_location("aicheck_test_client", Path(__file__).resolve().parents[1] / "scripts/aicheck_client.py")
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


class ProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, data=None, status=200, code=0, message=None):
                payload = {"code": code, "data": data, "operationId": "TEST-OP"}
                if message:
                    payload["message"] = message
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                cls.state["requests"].append(("GET", self.path, dict(self.headers)))
                path = urlsplit(self.path).path
                if cls.state.get("redirect"):
                    self.send_response(302)
                    self.send_header("Location", cls.other_url + "/unexpected?signature=hidden")
                    self.end_headers()
                    return
                if cls.state.get("business_error"):
                    return self.send({"reason": "AUTH_REQUIRED"}, code=401,
                                     message="expired test-secret https://store.example/file?signature=hidden")
                if "/inspection-services/" in path and cls.state.get("missing_capability"):
                    return self.send(status=404, code=40404)
                if path == "/api/inspection-services/capabilities":
                    return self.send({"mode": "local-input-only", "retention": {"serverStoresInput": False}})
                if path == "/api/inspection-services/rules":
                    return self.send({"source": "server", "nodes": [{"nodeId": 24, "code": "R24"}]})
                if path == "/api/knowledge/clauses":
                    return self.send({"items": [{"fileId": "K1", "clauseNo": "2.1", "standardName": "fixture"}], "total": 1})
                if path == "/api/knowledge/files/K1/canonical":
                    if cls.state.get("missing_standard"):
                        return self.send(code=40404, message="No canonical record")
                    return self.send({"document": {"id": "K1"}, "blocks": [{"pageNo": 2, "text": "test standard full text"}],
                                      "provenance": [{"sourceId": "SOURCE", "pageNo": 2}]})
                return self.send(status=404, code=40404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                cls.state["requests"].append(("POST", self.path, dict(self.headers), body))
                path = urlsplit(self.path).path
                if path == "/api/auth/login":
                    return self.send({"token": "fresh-token", "user": {"id": "U"}})
                if "/inspection-services/" in path and cls.state.get("missing_capability"):
                    return self.send(status=404, code=40404)
                if path == "/api/inspection-services/certificate-validity":
                    return self.send({"result": "evidence_insufficient" if not body["certificates"] else "passed",
                                      "authenticityChecked": False})
                if path == "/api/inspection-services/certificate-registry":
                    return self.send({"kind": body["kind"], "records": [], "authenticityConclusion": "manual_confirmation_required"})
                if path == "/api/std-samr/standards/verify":
                    return self.send({"status": "COMPLETED", "citedRef": body["standardRef"], "verdict": "current",
                                      "matched": {"detailUrl": "https://std.samr.gov.cn/gb/search/gbDetailed?id=PUBLIC_STANDARD_001"}})
                return self.send(status=404, code=40404)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.other = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.other_url = f"http://127.0.0.1:{cls.other.server_port}"
        cls.threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (cls.server, cls.other)]
        for thread in cls.threads:
            thread.start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.other):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join()

    def setUp(self):
        self.state.clear()
        self.state["requests"] = []
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {"AICHECK_BASE_URL": self.base, "AICHECK_TOKEN": "test-secret",
                                                   "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def tearDown(self):
        # All tests enforce this invariant, including unavailable service and redirect paths.
        for request in self.state["requests"]:
            self.assertNotIn("/projects", request[1])
            self.assertNotIn("upload-session", request[1])
            self.assertNotIn("/mineru/", request[1])
            self.assertNotIn("/ocr", request[1])
            self.assertNotIn("/tasks", request[1])
            self.assertNotIn("/runs", request[1])
            self.assertNotIn("Idempotency-Key", request[2])

    def test_catalog_has_only_review_tools_and_no_project_fields(self):
        self.assertEqual(set(client.ACTIONS), {"connection", "standards", "standard_content", "standard_status",
                                               "rules", "certificate_validity", "certificate_registry"})
        for action in client.ACTIONS.values():
            for field in ("projectId", "documentId", "versionId", "operationKey", "runId", "filePath", "contentBase64"):
                self.assertNotIn(field, json.dumps(action["inputSchema"]))

    def test_legacy_actions_and_extra_project_arguments_are_rejected_locally(self):
        for old in ("projects", "documents", "evidence", "download", "upload", "analyze", "start", "runs", "ocr"):
            self.assertEqual(client.invoke(old, {})["error"]["code"], "unknownAction")
        self.assertEqual(client.invoke("connection", {"projectId": "P"})["error"]["code"], "invalidArguments")
        self.assertEqual(self.state["requests"], [])

    def test_connection_calls_only_stateless_capabilities_with_auth(self):
        result = client.invoke("connection", {})
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["data"]["retention"]["serverStoresInput"])
        self.assertEqual(len(self.state["requests"]), 1)
        method, path, headers = self.state["requests"][0]
        self.assertEqual((method, path), ("GET", "/api/inspection-services/capabilities"))
        self.assertEqual(headers["Authorization"], "Bearer test-secret")

    def test_business_error_http_200_is_failure_and_redacted(self):
        self.state["business_error"] = True
        result = client.invoke("connection", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "401")
        self.assertNotIn("test-secret", json.dumps(result))
        self.assertNotIn("signature=", json.dumps(result))

    def test_public_standard_sources_preserved_without_loosening_signed_url_redaction(self):
        instance = client.Client()
        for path in ("/gb/search/gbDetailed", "/hb/search/stdHBDetailed", "/db/search/stdDBDetailed"):
            url = "https://std.samr.gov.cn" + path + "?id=PUBLIC_ABC-123"
            self.assertEqual(instance.safe({"detailUrl": url})["detailUrl"], url)
        for url in ("https://storage.example/original.pdf?signature=private-signature",
                    "http://127.0.0.1/private-storage/1", "https://std.samr.gov.cn.evil.example/gb/search/gbDetailed?id=ID",
                    "https://user:password@std.samr.gov.cn/gb/search/gbDetailed?id=ID",
                    "https://std.samr.gov.cn:8443/gb/search/gbDetailed?id=ID",
                    "https://std.samr.gov.cn/gb/search/gbDetailed?id=ID&token=private-token",
                    "https://std.samr.gov.cn/gb/search/gbDetailed?id=ID&X-Amz-Signature=private-signature",
                    "https://std.samr.gov.cn/gb/search/gbDetailed?id=ID&%74oken=private-token",
                    "https://std.samr.gov.cn/private-storage/original.pdf?id=ID",
                    "HTTP://STORAGE.EXAMPLE/ORIGINAL.PDF?signature=private-signature"):
            with self.subTest(url=url):
                self.assertEqual(instance.safe(url), "[server URL redacted]")
        self.assertEqual(self.state["requests"], [])

    def test_actual_secret_redacted_even_in_public_source_or_unexpected_field(self):
        instance = client.Client()
        result = instance.safe({"detailUrl": "https://std.samr.gov.cn/gb/search/gbDetailed?id=test-secret",
                                "other": "credential is test-secret", "token": "another-secret"})
        self.assertNotIn("test-secret", json.dumps(result))
        self.assertNotIn("another-secret", json.dumps(result))
        self.assertEqual(result["detailUrl"], "[server URL redacted]")
        self.assertEqual(instance.safe("https://std.samr.gov.cn/gb/search/gbDetailed?id=test%2Dsecret"), "[server URL redacted]")

    def test_missing_service_is_explicit_with_no_legacy_fallback(self):
        self.state["missing_capability"] = True
        for name, arguments in (("connection", {}), ("rules", {"source": "server", "nodeId": 24}),
                                ("certificate_validity", {"certificates": [], "referenceDate": "2026-09-22"})):
            with self.subTest(action=name):
                before = len(self.state["requests"])
                result = client.invoke(name, arguments)
                self.assertTrue(result["error"]["capabilityUnavailable"])
                self.assertEqual(len(self.state["requests"]), before + 1)

    def test_ocr_is_rejected_locally_without_reading_user_file(self):
        with patch.object(client.Path, "open", side_effect=AssertionError("must not read project file")):
            result = client.invoke("ocr", {"filePath": "/private/user-engineering.pdf"})
        self.assertEqual(result["error"]["code"], "unknownAction")
        self.assertEqual(self.state["requests"], [])

    def test_rules_local_without_network_and_server_without_project(self):
        with patch.dict(os.environ, {}, clear=True):
            result = client.invoke("rules", {"nodeId": 24})
        self.assertEqual(result["data"]["source"], "local")
        self.assertEqual(result["data"]["nodes"][0]["nodeId"], 24)
        self.assertEqual(self.state["requests"], [])
        result = client.invoke("rules", {"source": "server", "nodeId": 24})
        self.assertEqual(result["data"]["source"], "server")
        query = parse_qs(urlsplit(self.state["requests"][-1][1]).query)
        self.assertEqual(query, {"nodeId": ["24"]})

    def test_standards_search_pagination_uses_keyword_and_no_project(self):
        result = client.invoke("standards", {"query": "焊工", "page": 2, "pageSize": 200})
        self.assertTrue(result["ok"], result)
        self.assertEqual(parse_qs(urlsplit(self.state["requests"][-1][1]).query),
                         {"keyword": ["焊工"], "page": ["2"], "pageSize": ["200"]})
        self.assertTrue(result["data"]["warnings"])
        self.assertEqual(client.invoke("standards", {"query": "焊工", "pageSize": 201})["error"]["code"], "invalidArguments")

    def test_standard_canonical_keeps_provenance_and_missing_is_not_summary_fallback(self):
        args = {"fileId": "K1", "pageNo": 2, "section": "2.1"}
        result = client.invoke("standard_content", args)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["provenance"][0]["sourceId"], "SOURCE")
        query = parse_qs(urlsplit(self.state["requests"][-1][1]).query)
        self.assertEqual(query["includeBlocks"], ["true"])
        self.assertEqual(query["includeHistory"], ["false"])
        self.assertEqual(query["section"], ["2.1"])
        self.state["missing_standard"] = True
        self.assertEqual(client.invoke("standard_content", args)["error"]["code"], "standardEvidenceUnavailable")

    def test_standard_status_sends_only_reference_and_optional_date(self):
        arguments = {"standardRef": "GB/T 20801.1-2020", "reviewDate": "2026-09-22"}
        result = client.invoke("standard_status", arguments)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.state["requests"][-1][:2], ("POST", "/api/std-samr/standards/verify"))
        self.assertEqual(self.state["requests"][-1][3], arguments)
        self.assertEqual(result["data"]["matched"]["detailUrl"],
                         "https://std.samr.gov.cn/gb/search/gbDetailed?id=PUBLIC_STANDARD_001")

    def test_certificate_validity_transmits_minimal_extracted_fields(self):
        arguments = {"certificates": [{"certificateNo": "TEST-01", "holder": "测试单位", "validFrom": "2024-01-01",
                                       "validUntil": "2027-01-01", "scopes": ["GC2"]}],
                     "periodStart": "2026-01-01", "periodEnd": "2026-10-01", "expectedHolder": "测试单位", "requiredScopes": ["GC2"]}
        result = client.invoke("certificate_validity", arguments)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["data"]["authenticityChecked"])
        self.assertEqual(self.state["requests"][-1][3], arguments)
        empty = client.invoke("certificate_validity", {"certificates": [], "referenceDate": "2026-09-22"})
        self.assertEqual(empty["data"]["result"], "evidence_insufficient")

    def test_certificate_requires_explicit_valid_business_date_before_network(self):
        for arguments in ({"certificates": []}, {"certificates": [], "periodStart": "2026-01-01"},
                          {"certificates": [], "referenceDate": "2026-02-30"},
                          {"certificates": [], "periodStart": "2026-10-01", "periodEnd": "2026-01-01"},
                          {"certificates": [{"validUntil": "2026-02-30"}], "referenceDate": "2026-09-22"}):
            with self.subTest(arguments=arguments):
                self.assertEqual(client.invoke("certificate_validity", arguments)["error"]["code"], "invalidArguments")
        self.assertEqual(self.state["requests"], [])

    def test_certificate_fields_refuse_injected_platform_verification_and_documents(self):
        for row in ({"platformVerification": {"outcome": "verified_match"}}, {"filePath": "/private/document.pdf"}):
            self.assertFalse(client.invoke("certificate_validity", {"certificates": [row]})["ok"])
        self.assertFalse(client.invoke("certificate_validity", {"certificates": [], "referenceDate": "today"})["ok"])
        self.assertEqual(self.state["requests"], [])

    def test_registry_requires_explicit_external_query_consent(self):
        arguments = {"kind": "organization_license", "identifier": "TS0000000-2026"}
        self.assertFalse(client.invoke("certificate_registry", arguments)["ok"])
        self.assertFalse(client.invoke("certificate_registry", {**arguments, "allowExternalQuery": False})["ok"])
        self.assertFalse(client.invoke("certificate_registry", {**arguments, "allowExternalQuery": 1})["ok"])
        self.assertEqual(self.state["requests"], [])
        result = client.invoke("certificate_registry", {**arguments, "allowExternalQuery": True})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["authenticityConclusion"], "manual_confirmation_required")
        self.assertEqual(len(self.state["requests"]), 1)

    def test_api_redirect_rejected_without_retry_or_auth_leak(self):
        self.state["redirect"] = True
        result = client.invoke("connection", {})
        self.assertEqual(result["error"]["code"], "redirectRejected")
        self.assertEqual(len(self.state["requests"]), 1)
        self.assertFalse(any("unexpected" in row[1] for row in self.state["requests"]))

    def test_cross_origin_requests_never_receive_auth_even_if_supplied(self):
        instance = client.Client()
        with instance.open("GET", self.other_url + "/api/inspection-services/capabilities",
                           headers={"Authorization": "other-token", "Cookie": "session=private", "Proxy-Authorization": "proxy-token"}) as response:
            self.assertEqual(response.status, 200)
        headers = self.state["requests"][-1][2]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("Proxy-Authorization", headers)

    def test_configuration_rejects_remote_http_and_credentials_in_url(self):
        with patch.dict(os.environ, {"AICHECK_BASE_URL": "http://private.example"}):
            self.assertEqual(client.invoke("connection", {})["error"]["code"], "insecureTransport")
        with patch.dict(os.environ, {"AICHECK_BASE_URL": "https://user:password@example.com"}):
            self.assertEqual(client.invoke("connection", {})["error"]["code"], "invalidUrl")
        self.assertEqual(self.state["requests"], [])

    def test_token_file_and_secure_interactive_login(self):
        token_file = Path(self.directory.name) / "token"
        with patch.dict(os.environ, {"AICHECK_TOKEN": "", "AICHECK_TOKEN_FILE": str(token_file)}), patch.object(client.getpass, "getpass", return_value="password"):
            result = client.login("inspector", str(token_file), "tenant")
            self.assertNotIn("fresh-token", json.dumps(result))
            self.assertEqual(token_file.read_text().strip(), "fresh-token")
            self.assertEqual(stat.S_IMODE(token_file.stat().st_mode), 0o600)
            self.assertTrue(client.invoke("connection", {})["ok"])
            self.assertEqual(self.state["requests"][-1][2]["Authorization"], "Bearer fresh-token")
        login_request = next(row for row in self.state["requests"] if row[0] == "POST")
        self.assertNotIn("Authorization", login_request[2])
        self.assertEqual(login_request[3]["tenantId"], "tenant")


if __name__ == "__main__":
    unittest.main()
