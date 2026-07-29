from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from .render_common import output_file_name


NODE = Path(
    "/Users/hankieyooly/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/node/bin/node"
)


def render_xlsx(content: dict, master: dict, output: Path) -> Path:
    del master  # Workbook payload is self-contained.
    output.mkdir(parents=True, exist_ok=True)
    destination = output / output_file_name(content, "xlsx")
    preview_dir = output / ".xlsx-previews" / destination.stem
    script = Path(__file__).with_name("render_xlsx.mjs")
    with tempfile.TemporaryDirectory(prefix="r01-r69-xlsx-") as temp:
        payload = Path(temp) / "payload.json"
        payload.write_text(
            json.dumps(content, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        subprocess.run(
            [str(NODE), str(script), str(payload), str(destination), str(preview_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    return destination

