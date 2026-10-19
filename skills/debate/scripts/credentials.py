"""Read existing keys at call time; never copy credentials into debate state."""
import json
import os
import re
from pathlib import Path

from providers import DebateError

TOKENHUB_BASES = {
    ("cn", "gz"): "https://tokenhub.tencentmaas.com/v1",
    ("cn", "sg"): "https://tokenhub-intl.tencentmaas.com/v1",
    ("intl", "gz"): "https://tokenhub.tencentcloudmaas.com/v1",
    ("intl", "sg"): "https://tokenhub-intl.tencentcloudmaas.com/v1",
}


def validate_source(p):
    source = p.get("thcli_key")
    if source is None:
        return
    if p["provider"] != "tokenhub" or not isinstance(source, dict):
        raise DebateError("thcli_key 仅供 tokenhub 参与者使用")
    if set(source) != {"profile", "site", "area", "alias"}:
        raise DebateError("thcli_key 必须明确填写 profile、site、area、alias")
    if any(not isinstance(source[k], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", source[k]) for k in source):
        raise DebateError("thcli_key 配置无效")
    expected = TOKENHUB_BASES.get((source["site"], source["area"]))
    if not expected or p["base_url"].rstrip("/") != expected:
        raise DebateError("TokenHub base_url 与 thcli_key 的站点/地域不匹配；不会向其他地址发送 CLI 密钥")


def resolve_key(p):
    validate_source(p)
    key = os.environ.get(p["api_key_env"], "")
    if key:
        return key
    source = p.get("thcli_key")
    if not source:
        return ""
    path = Path.home() / ".thcli" / (source["profile"] + ".tokenhub.json")
    if not path.exists():
        return ""
    try:
        if path.stat().st_mode & 0o077:
            raise DebateError("TokenHub 本地密钥文件须限制为 600 权限")
        data = json.loads(path.read_text(encoding="utf-8"))
        key = data.get("sites", {}).get(source["site"], {}).get(source["area"], {}).get("th", {}).get(source["alias"], "")
    except (OSError, ValueError, AttributeError):
        raise DebateError("无法读取 TokenHub 本地密钥配置；请检查 thcli chat-config get") from None
    if not isinstance(key, str):
        raise DebateError("TokenHub 本地密钥结构不兼容；请检查 CLI 配置")
    return key
