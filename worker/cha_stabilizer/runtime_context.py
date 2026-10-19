"""由可信 Worker 构造、不得由 HTTP 请求反序列化的运行上下文。"""
from dataclasses import dataclass
from pathlib import Path

from .paths import validate_run_directory


@dataclass(frozen=True)
class RunnerContext:
    data_root: Path
    runs_root: Path
    resource_root: Path
    job_id: str
    production: bool

    def validate(self, workdir: Path) -> Path:
        # DesktopData 与源码目录不同；只接受本次 JobStore 已选择的 UUID 根。
        expected_runs = self.data_root / "private" / "runs"
        if self.runs_root.resolve(strict=True) != expected_runs.resolve(strict=True):
            raise ValueError("runner data root and runs root do not agree")
        return validate_run_directory(Path(workdir), self.runs_root, self.job_id)
