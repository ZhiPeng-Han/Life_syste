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


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    """仓库里的默认值（config/）+ 你自己的修改（data/ 下的同名文件，只写想改的部分）。

    个人修改放在 data/ 里，不进 git，所以 git pull 更新系统时永远不会冲突；
    仓库新增的配置项也会自动生效。列表（如 [[blocks]]）整体以你的为准。
    """
    data: dict = {}
    for base in (config_dir(), home()):
        path = base / name
        if path.exists():
            with open(path, "rb") as f:
                data = _merge(data, tomllib.load(f))
    return data


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
