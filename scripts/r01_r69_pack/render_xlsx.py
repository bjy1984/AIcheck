from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from .render_common import output_file_name
from .test_seal import render_test_seal_png, signature_contract


NODE = Path(
    "/Users/hankieyooly/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/node/bin/node"
)


def render_xlsx(content: dict, master: dict, output: Path) -> Path:
    del master  # Workbook payload is self-contained.
    payload_content = deepcopy(content)
    contract = signature_contract(payload_content)
    seal_bytes = render_test_seal_png(contract["label"], contract["role"])
    payload_content["signature_contract"] = {
        **contract,
        "data_url": "data:image/png;base64,"
        + base64.b64encode(seal_bytes).decode("ascii"),
    }
    output.mkdir(parents=True, exist_ok=True)
    destination = output / output_file_name(content, "xlsx")
    preview_dir = (
        Path.cwd() / "tmp/r01-r69-xlsx-previews" / destination.stem
    )
    script = Path(__file__).with_name("render_xlsx.mjs")
    with tempfile.TemporaryDirectory(prefix="r01-r69-xlsx-") as temp:
        payload = Path(temp) / "payload.json"
        payload.write_text(
            json.dumps(payload_content, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        subprocess.run(
            [str(NODE), str(script), str(payload), str(destination), str(preview_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    inspect_log = destination.with_name(destination.name + ".inspect.ndjson")
    if inspect_log.exists():
        preview_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(inspect_log), str(preview_dir / inspect_log.name))
    return destination
