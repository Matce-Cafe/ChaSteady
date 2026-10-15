"""Read-only golden comparison, optionally render three new owned C7037 previews."""
import argparse
import json
from pathlib import Path
import sys
import threading
import uuid

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

import numpy as np
from cha_stabilizer.core.cache import load_legacy
from cha_stabilizer.core.fusion import anchored_blend, interval_gains
from cha_stabilizer.core.pipeline import run_fusion, write_json
from cha_stabilizer.development_config import load_development_config
from cha_stabilizer.job_runner import C7037_EXPERIMENT_DIR, discover_c7037_presets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    development = load_development_config(ROOT, enabled=True)
    data_root_value = development.get("c7037_data_root")
    if not data_root_value:
        raise RuntimeError("private/dev_worker_config.json must explicitly select the C7037 development data root")
    parent = ROOT / "private" / "runs" / ("regression-" + uuid.uuid4().hex)
    parent.mkdir()
    rows = []
    lab = Path(data_root_value) / C7037_EXPERIMENT_DIR
    presets = discover_c7037_presets(str(lab))
    slugs = ("zoomin-140-156", "fixed400-212-228", "zoomout-230-246")
    if len(presets) != len(slugs):
        raise RuntimeError("the explicitly selected C7037 root did not discover all pinned cache pairs")
    for preset, slug in zip(presets, slugs):
        request = preset["request"]
        quiet, reference, provenance = load_legacy(
            request, (1280, 720), 50., discovery_binding=preset
        )
        gain = interval_gains(request["start"], 800, 50., request["reference_intervals"])
        result = anchored_blend(quiet, reference, gain)
        golden = lab / "analysis" / ("ctb_target_fusion_v9_known_windows_20261013_" + slug + ".npz")
        with np.load(golden, allow_pickle=False) as data:
            error = float(np.max(np.abs(result.matrices - data["render_source_origin_unit_affines_1280"])))
            weight_error = float(np.max(np.abs(result.actual_gain - data["actual_reference_gain"])))
        if error > 1e-9 or weight_error > 1e-10:
            raise RuntimeError("Ported V9 differs from the approved golden trajectory: " + slug)
        row = {"window": slug, "matrix_max_absolute_error": error, "weight_max_absolute_error": weight_error,
               "scope": "mathematical_port_regression_not_perceptual_validation", "cache": provenance}
        print(json.dumps(row), flush=True)
        if args.render:
            workdir = parent / slug
            workdir.mkdir()
            tools = {
                "ffmpeg": Path(development["tool_paths"]["ffmpeg"]) if development["tool_paths"]["ffmpeg"] else None,
                "ffprobe": Path(development["tool_paths"]["ffprobe"]) if development["tool_paths"]["ffprobe"] else None,
                "_cached_v9_discovery_binding": preset,
            }
            callback = lambda stage, progress, message: print(json.dumps({"window": slug, "stage": stage,
                                                                         "progress": progress, "message": message}, ensure_ascii=False), flush=True)
            rendered = run_fusion(request, workdir, tools, threading.Event(), callback)
            row["output"] = str(rendered["outputs"][0]["path"])
            row["validation"] = rendered["validation"]
            print(json.dumps({"window": slug, "output": row["output"], "status": rendered["validation"]["status"]}), flush=True)
        rows.append(row)
    report = parent / "regression.json"
    write_json(report, rows)
    print(str(report), flush=True)


if __name__ == "__main__":
    main()
