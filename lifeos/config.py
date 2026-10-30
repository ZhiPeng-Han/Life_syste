"""路径与配置加载。个人数据默认放在仓库的 data/ 目录（已被 .gitignore 排除）。"""

import os
import tomllib
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def home() -> Path:
    path = Path(os.environ.get("LIFEOS_HOME", REPO_ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return home() / "lifeos.db"


def config_dir() -> Path:
    return Path(os.environ.get("LIFEOS_CONFIG", REPO_ROOT / "config"))


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    # data/ 下的同名文件优先，方便个人覆盖而不改仓库默认值
    for base in (home(), config_dir()):
        path = base / name
        if path.exists():
            with open(path, "rb") as f:
                return tomllib.load(f)
    return {}


def rules() -> dict:
    return _load("rules.toml")


def recipes() -> list[dict]:
    return _load("recipes.toml").get("recipe", [])


def reload() -> None:
    _load.cache_clear()


def currency() -> str:
    return rules().get("general", {}).get("currency", "£")


def domains() -> dict:
    return rules().get("domains", {})


def domain_weight(domain: str) -> float:
    role = domains().get(domain, {}).get("role", "side")
    return {"main": 1.5, "side": 1.0, "frozen": 0.3}.get(role, 1.0)
