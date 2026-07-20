from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "ai_studio_code (1).html"
JS_PATH = ROOT / "harness.js"
CSS_PATH = ROOT / "harness.css"


class HarnessHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.inline_scripts = []
        self.meta_csp = None
        self.script_sources = []
        self._inside_inline_script = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        if tag == "meta" and attributes.get("http-equiv", "").lower() == (
            "content-security-policy"
        ):
            self.meta_csp = attributes.get("content")
        if tag == "script":
            source = attributes.get("src")
            if source:
                self.script_sources.append(source)
            else:
                self._inside_inline_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._inside_inline_script = False

    def handle_data(self, data):
        if self._inside_inline_script and data.strip():
            self.inline_scripts.append(data)


def read_sources():
    return (
        HTML_PATH.read_text(encoding="utf-8"),
        JS_PATH.read_text(encoding="utf-8"),
        CSS_PATH.read_text(encoding="utf-8"),
    )


def parse_html():
    parser = HarnessHtmlParser()
    parser.feed(HTML_PATH.read_text(encoding="utf-8"))
    return parser


def test_required_dom_and_external_assets_exist():
    parser = parse_html()
    assert {"button", "captcha-element", "harness-status"} <= parser.ids
    assert parser.inline_scripts == []
    assert parser.script_sources == ["./harness.js"]
    assert CSS_PATH.is_file()


def test_csp_rejects_script_eval_and_limits_vendor_origins():
    csp = parse_html().meta_csp
    assert csp is not None
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "form-action 'none'" in csp
    assert "'unsafe-eval'" not in csp

    script_directive = re.search(r"script-src ([^;]+)", csp)
    assert script_directive
    assert "'unsafe-inline'" not in script_directive.group(1)
    assert script_directive.group(1).split() == [
        "'self'",
        "https://o.alicdn.com",
        "https://g.alicdn.com",
    ]


def test_uses_official_popup_initialization_contract():
    _, javascript, _ = read_sources()
    assert (
        '"https://o.alicdn.com/captcha-frontend/aliyunCaptcha/'
        'AliyunCaptcha.js"' in javascript
    )
    assert "window.AliyunCaptchaConfig" in javascript
    assert "window.initAliyunCaptcha({" in javascript
    assert 'mode: "popup"' in javascript
    assert 'button: "#button"' in javascript
    assert 'element: "#captcha-element"' in javascript
    for callback in ("success", "fail", "onError", "getInstance"):
        assert re.search(rf"\b{callback}:\s*", javascript)


def test_state_bridge_is_redacted_and_token_is_one_time():
    _, javascript, _ = read_sources()
    assert "const MAX_CLIENT_TOKEN_LENGTH = 64000;" in javascript
    assert 'Object.defineProperty(window, "__captchaHarness"' in javascript
    assert 'Object.defineProperty(window, "__captchaHarnessState"' in javascript
    assert "consumeClientToken: consumeClientToken" in javascript
    assert "getState: getState" in javascript

    get_state = javascript.split("function getState()", 1)[1].split(
        "function consumeClientToken", 1
    )[0]
    assert "clientToken" not in get_state
    assert "attemptId:" in get_state
    assert "status:" in get_state
    assert "updatedAt:" in get_state
    assert "error:" in get_state

    consume = javascript.split("function consumeClientToken", 1)[1].split(
        "function setStatus", 1
    )[0]
    assert "requestedAttemptId !== internalState.attemptId" in consume
    assert re.search(r"const token = clientToken;\s+clientToken = null;", consume)
    assert "return token;" in consume


def test_query_configuration_is_allowlisted_and_validated():
    _, javascript, _ = read_sources()
    for key in (
        "attemptId",
        "language",
        "prefix",
        "region",
        "sceneId",
        "userCertifyId",
    ):
        assert f'"{key}"' in javascript
    assert "UNKNOWN_QUERY_PARAMETER" in javascript
    assert "DUPLICATE_QUERY_PARAMETER" in javascript
    assert "INVALID_ATTEMPT_ID" in javascript
    assert "INVALID_PREFIX" in javascript
    assert "INVALID_SCENE_ID" in javascript
    assert "INVALID_REGION" in javascript
    assert "INVALID_LANGUAGE" in javascript
    assert "INVALID_USER_CERTIFY_ID" in javascript
    assert "MISSING_ATTEMPT_ID" not in javascript  # assembled without embedding credentials
    assert "no8xfe" not in javascript
    assert "36qgs6xb" not in javascript


def test_legacy_and_unsafe_execution_paths_are_absent():
    html, javascript, css = read_sources()
    combined = "\n".join((html, javascript, css))
    forbidden = (
        "calculate_distance.py",
        "Python命令",
        "innerHTML",
        "window.fetch =",
        "XMLHttpRequest.prototype",
        "HTMLImageElement.prototype",
        "new MouseEvent",
        "dispatchEvent(",
        "direct-set-shadow",
        "deep-analyze",
        "precise-calc",
        "localStorage",
        "sessionStorage",
        "console.log",
        "console.error",
        "shell=True",
    )
    for marker in forbidden:
        assert marker not in combined


def test_token_is_never_rendered_or_logged():
    html, javascript, _ = read_sources()
    assert "captchaVerifyParam" not in html
    assert "console." not in javascript
    render_status = javascript.split("function renderStatus", 1)[1]
    assert "clientToken" not in render_status
    assert "captchaVerifyParam" not in render_status


def test_runtime_bridge_redacts_and_consumes_token_once():
    script = textwrap.dedent(
        r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const webcrypto = require("crypto").webcrypto;

        let initOptions = null;
        const button = {
          disabled: true,
          listeners: Object.create(null),
          addEventListener(name, handler) { this.listeners[name] = handler; },
        };
        const status = {
          classList: { toggle() {} },
          textContent: "",
        };
        const elements = {
          "button": button,
          "captcha-element": {},
          "harness-status": status,
        };

        global.document = {
          readyState: "complete",
          getElementById(id) { return elements[id] || null; },
          createElement(tag) {
            assert.strictEqual(tag, "script");
            return {
              listeners: Object.create(null),
              addEventListener(name, handler) { this.listeners[name] = handler; },
            };
          },
          head: {
            appendChild(node) {
              global.window.initAliyunCaptcha = function (options) {
                initOptions = options;
                options.getInstance({});
              };
              node.listeners.load();
            },
          },
        };
        global.window = {
          crypto: webcrypto,
          location: {
            search: "?attemptId=attempt_12345678&sceneId=scene_1234&prefix=prefix01&region=cn&language=cn&userCertifyId=prefix01_Ab3dE5fG7h",
          },
          setTimeout(callback) { callback(); },
        };

        vm.runInThisContext(fs.readFileSync("harness.js", "utf8"), {
          filename: "harness.js",
        });

        assert.strictEqual(window.__captchaHarness.getState().status, "READY");
        assert.strictEqual(button.disabled, false);
        assert.strictEqual(initOptions.mode, "popup");
        assert.strictEqual(initOptions.button, "#button");
        assert.strictEqual(initOptions.element, "#captcha-element");
        assert.strictEqual(initOptions.UserCertifyId, "prefix01_Ab3dE5fG7h");

        button.listeners.click({
          isTrusted: true,
          preventDefault() {},
          stopImmediatePropagation() {},
        });
        assert.strictEqual(
          window.__captchaHarness.getState().status,
          "CHALLENGE_OPEN"
        );

        initOptions.success("secret-client-token");
        const snapshot = window.__captchaHarness.getState();
        assert.strictEqual(snapshot.status, "CLIENT_PASS");
        assert.strictEqual(JSON.stringify(snapshot).includes("secret-client-token"), false);
        assert.strictEqual(status.textContent.includes("secret-client-token"), false);
        assert.strictEqual(
          window.__captchaHarness.consumeClientToken("wrong-attempt"),
          null
        );
        assert.strictEqual(
          window.__captchaHarness.consumeClientToken("attempt_12345678"),
          "secret-client-token"
        );
        assert.strictEqual(
          window.__captchaHarness.consumeClientToken("attempt_12345678"),
          null
        );
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_invalid_query_fails_closed_before_sdk_load():
    script = textwrap.dedent(
        r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");

        let sdkAppended = false;
        const status = {
          classList: { toggle() {} },
          textContent: "",
        };
        global.document = {
          readyState: "complete",
          getElementById(id) { return id === "harness-status" ? status : null; },
          head: { appendChild() { sdkAppended = true; } },
        };
        global.window = {
          crypto: require("crypto").webcrypto,
          location: {
            search: "?attemptId=attempt_12345678&prefix=prefix01&sceneId=bad%20scene&userCertifyId=prefix01_Ab3dE5fG7h",
          },
        };

        vm.runInThisContext(fs.readFileSync("harness.js", "utf8"), {
          filename: "harness.js",
        });

        const snapshot = window.__captchaHarness.getState();
        assert.strictEqual(snapshot.status, "ERROR");
        assert.strictEqual(snapshot.error.source, "config");
        assert.strictEqual(snapshot.error.code, "INVALID_SCENE_ID");
        assert.strictEqual(sdkAppended, false);
        assert.strictEqual(window.AliyunCaptchaConfig, undefined);
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_missing_query_fails_closed_before_sdk_load():
    script = textwrap.dedent(
        r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");

        let sdkAppended = false;
        const status = { classList: { toggle() {} }, textContent: "" };
        global.document = {
          readyState: "complete",
          getElementById(id) { return id === "harness-status" ? status : null; },
          head: { appendChild() { sdkAppended = true; } },
        };
        global.window = {
          crypto: require("crypto").webcrypto,
          location: { search: "" },
        };

        vm.runInThisContext(fs.readFileSync("harness.js", "utf8"), {
          filename: "harness.js",
        });
        const snapshot = window.__captchaHarness.getState();
        assert.strictEqual(snapshot.status, "ERROR");
        assert.strictEqual(snapshot.error.source, "config");
        assert.strictEqual(snapshot.error.code, "MISSING_ATTEMPT_ID");
        assert.strictEqual(snapshot.attemptId, "invalid-config");
        assert.strictEqual(sdkAppended, false);
        assert.strictEqual(window.AliyunCaptchaConfig, undefined);
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


if __name__ == "__main__":
    tests = sorted(
        (name, value)
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    )
    for _, test in tests:
        test()
    print(f"{len(tests)} harness contract tests passed")
