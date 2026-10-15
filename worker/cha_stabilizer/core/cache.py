"""Only the six explicitly approved C7037 trajectory caches, never arbitrary pickle."""
import hashlib
from pathlib import Path
import zipfile

import numpy as np

from ..errors import NeedsReviewError
from .geometry import check_unit
from .media import local_file


HASHES = {
    "CTB_TRANSLATION_ZOOM_IN_140-156_SIGMA_0.90.npz": "ddc8b16bed33df2d24d0506ac3a2bbd97bda01c300daf550df82b8122b35ebd3",
    "CTB_TRANSLATION_FIXED400_212-228_SIGMA_1.30.npz": "89f36fe73a65d525df9336dc2a1cf71a7e0f4059c2458f6da7830c5751427600",
    "CTB_RAFT_GLOBAL_TRANSLATION_ZOOM_OUT_230-246.npz": "b1b2af69e62766c5f3ad99598ca6a676237f44397309605fb158a5414d794de1",
    "ctb_rigid_gf_reference_full_v7_20261013_zoomin-140-156.npz": "e1d7ed81e44fcaeabc179e127ea24d5424c29a8cf081fe9d1098bab30aa1d88a",
    "ctb_rigid_gf_reference_full_v7_20261013_fixed400-212-228.npz": "fa2a2054f0e9f57253086bed5a94f5eca141abf3b691fb1419bc83a3a8423b13",
    "ctb_rigid_gf_reference_full_v7_20261013_zoomout-230-246.npz": "c5c1e909af6b5cf7342d05ab016d40860675a2dcd270b9db50dfc5e0945f1e90",
}


def checked_cache(path):
    path = local_file(path, {".npz"})
    if path.name not in HASHES or path.stat().st_size > 16 * 1024 ** 2:
        raise NeedsReviewError("缓存不是本机明确批准的V9复现输入")
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != HASHES[path.name]:
        raise NeedsReviewError("历史缓存摘要已改变，禁止当作批准的旧轨迹使用")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (len(entries) > 64 or sum(i.file_size for i in entries) > 64 * 1024 ** 2 or
                any(i.file_size > 16 * 1024 ** 2 or not i.filename.endswith(".npy") for i in entries)):
            raise NeedsReviewError("缓存归档超出安全尺寸或类型限制")
    return path, digest


def load_legacy(request, size, fps, discovery_binding=None):
    # Standalone callers must provide the worker's explicit user-discovery
    # binding; cache SHA pins alone do not authorize an arbitrary path pairing.
    if not isinstance(discovery_binding, dict):
        raise NeedsReviewError("Cached V9 requires an active user-discovery binding.")
    from ..job_runner import validate_cached_v9_discovery
    try:
        validate_cached_v9_discovery(request, discovery_binding)
    except (OSError, ValueError) as exc:
        raise NeedsReviewError("The cached V9 discovery binding no longer matches its inputs.") from exc
    if size != (1280, 720) or fps != 50.:
        raise NeedsReviewError("旧轨迹仅支持原C7037的1280×720/50fps复现")
    quiet_path, qhash = checked_cache(request["legacy_quiet_cache"])
    reference_path, rhash = checked_cache(request["legacy_reference_cache"])
    count = round((request["end"] - request["start"]) * fps)
    with np.load(quiet_path, allow_pickle=False) as data:
        quiet = data["corrections"].copy()
        width, height = int(data["tracking_width"]), int(data["tracking_height"])
        if float(data["fps"]) != fps or quiet.shape != (count, 2, 3) or width <= 0 or height <= 0:
            raise NeedsReviewError("旧CTB缓存帧数、帧率或坐标尺寸不匹配")
        if abs(width / height - size[0] / size[1]) > 1e-5:
            raise NeedsReviewError("旧CTB缓存坐标纵横比不匹配")
        if not np.array_equal(quiet[:, :, :2], np.broadcast_to(np.eye(2), (count, 2, 2))):
            raise NeedsReviewError("旧CTB目标不是纯平移")
        quiet[:, :, 2] *= size[0] / width
    with np.load(reference_path, allow_pickle=False) as data:
        if not bool(data["all_frames_qualified"]) or not bool(data["unit_se2_all_frames"]):
            raise NeedsReviewError("旧参考轨迹存在未通过闸门的帧")
        if (float(data["fps"]) != fps or float(data["start_seconds"]) != request["start"] or
                float(data["end_seconds"]) != request["end"]):
            raise NeedsReviewError("旧GF参考缓存时间线不匹配")
        reference = data["render_source_origin_unit_affines_1280"].copy()
        if reference.shape != (count, 2, 3):
            raise NeedsReviewError("旧GF参考缓存帧数不匹配")
    check_unit(quiet)
    check_unit(reference)
    provenance = {"quiet_sha256": qhash, "reference_sha256": rhash,
                  "mode": "cached_v9", "fresh_measurement": False,
                  "legacy_quiet_tracking_gaps_disclosed": True}
    return quiet, reference, provenance
