""".env loader for the migration app.

Searches for .env in this order: the app's base directory, then that
directory's parent (the project root, where the existing
dmp_financesummary.csv/.env live in the dev checkout).

"Base directory" depends on how the code is running: under PyInstaller
--onefile, `__file__` resolves inside the temp extraction dir (_MEIPASS),
not next to the actual .exe, so a frozen build must instead use
`sys.executable`'s folder (PRD §11 Phase 9: ".env는 실행파일과 같은 폴더에서
읽도록 처리"). No third-party dependency (python-dotenv) is used, to keep
the app installable with zero extra packages.
"""
from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_KEYS = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _candidate_env_paths() -> list[Path]:
    base = _base_dir()
    return [base / ".env", base.parent / ".env"]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_env() -> dict[str, str]:
    for path in _candidate_env_paths():
        if path.is_file():
            values = _parse_env_file(path)
            missing = [k for k in REQUIRED_KEYS if k not in values]
            if missing:
                raise RuntimeError(f"{path}에 필수 키 누락: {missing}")
            return values
    raise FileNotFoundError(
        "'.env' 파일을 찾을 수 없습니다. 다음 위치를 확인하세요: "
        + ", ".join(str(p) for p in _candidate_env_paths())
    )


def mask_secret(value: str, keep_prefix: int = 6, keep_suffix: int = 4) -> str:
    if len(value) <= keep_prefix + keep_suffix:
        return "*" * len(value)
    return f"{value[:keep_prefix]}{'*' * (len(value) - keep_prefix - keep_suffix)}{value[-keep_suffix:]}"


class Config:
    def __init__(self) -> None:
        env = load_env()
        self.supabase_url: str = env["SUPABASE_URL"]
        self.supabase_service_role_key: str = env["SUPABASE_SERVICE_ROLE_KEY"]

    def __repr__(self) -> str:
        return (
            f"Config(supabase_url={self.supabase_url!r}, "
            f"supabase_service_role_key={mask_secret(self.supabase_service_role_key)!r})"
        )


if __name__ == "__main__":
    config = Config()
    print(config)
