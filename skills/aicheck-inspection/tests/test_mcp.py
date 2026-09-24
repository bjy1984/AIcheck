import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("inspection_mcp", SCRIPTS / "mcp_server.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.server = mcp.Server()
        self.call("initialize", {"protocolVersion": "2025-06-18"})

    def call(self, method, params=None):
        return self.server.dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})

    def test_discovery_and_local_rules_without_credentials(self):
        tools = self.call("tools/list")["result"]["tools"]
        self.assertTrue(any(tool["name"] == "aicheck_rules" for tool in tools))
        names = {tool["name"] for tool in tools}
        self.assertEqual(names, {"aicheck_" + name for name in (
            "connection", "rules", "standards", "standard_content", "standard_status",
            "certificate_validity", "certificate_registry",
        )})
        for tool in tools:
            self.assertNotIn("projectId", tool["inputSchema"].get("properties", {}))
        rules = self.call("tools/call", {"name": "aicheck_rules", "arguments": {"nodeId": 24}})
        self.assertNotIn("error", rules)
        result = rules["result"]
        self.assertFalse(result.get("isError"))
        self.assertIn("焊工", result["content"][0]["text"])

    def test_unknown_input_does_not_call_service(self):
        with patch.object(mcp, "invoke") as invoke:
            response = self.call("tools/call", {"name": "aicheck_rules", "arguments": {"nodeId": "twenty-four"}})
        self.assertEqual(response["error"]["code"], -32602)
        invoke.assert_not_called()

    def test_no_secrets_in_unexpected_exception(self):
        with patch.object(mcp, "invoke", side_effect=RuntimeError("Bearer SUPER_SECRET")):
            response = self.call("tools/call", {"name": "aicheck_rules", "arguments": {"nodeId": 24}})
        self.assertEqual(response["error"]["code"], -32603)
        self.assertNotIn("SUPER_SECRET", json.dumps(response))

    def test_business_failure_is_mcp_tool_error(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.call("tools/call", {"name": "aicheck_connection", "arguments": {}})
        result = response["result"]
        self.assertTrue(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["error"]["code"], "notConfigured")

    def test_resources_are_allowlisted(self):
        result = self.call("resources/read", {"uri": "aicheck://review-contract"})
        self.assertIn("证据不足", result["result"]["contents"][0]["text"])
        self.assertIn("error", self.call("resources/read", {"uri": "../../.env"}))

    def test_lifecycle_and_real_stdio_framing(self):
        commands = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "aicheck_rules", "arguments": {"nodeId": 4}}},
        ]
        completed = subprocess.run([sys.executable, str(SCRIPTS / "mcp_server.py")],
            input="\n".join(json.dumps(command) for command in commands) + "\n",
            text=True, capture_output=True, timeout=15, check=True)
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([item["id"] for item in responses], [1, 2, 3])
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2024-11-05")
        self.assertFalse(responses[-1]["result"].get("isError"))
        self.assertFalse(completed.stderr)


if __name__ == "__main__":
    unittest.main()
