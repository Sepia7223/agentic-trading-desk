from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_legacy_indicators_script_wrapper(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps({"close": [float(i) for i in range(1, 230)]}))

    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "indicators.py"), str(input_file)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)
    assert payload["n_bars"] == 229
    assert payload["ema200"] is not None
