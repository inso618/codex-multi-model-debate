#!/usr/bin/env python3
"""Create private configuration templates. No network and no credential reads."""
import argparse
import json
import os
from pathlib import Path

from debate import DEFAULT_CONFIG


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    config = Path(args.config).expanduser().resolve()
    if config.exists():
        parser.error('配置已存在，不覆盖；请编辑现有文件或使用 --config 指定新位置')
    env = config.parent / 'keys.env'
    if env.exists() and (not env.is_file() or env.stat().st_mode & 0o077):
        parser.error('已有 keys.env 必须是权限为 600 的普通文件；未修改文件')
    assets = Path(__file__).resolve().parents[1] / 'assets'
    template = json.loads((assets / 'providers.example.json').read_text(encoding='utf-8'))
    config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not env.exists():
        fd = os.open(str(env), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write((assets / 'keys.env.example').read_text(encoding='utf-8'))
    fd = os.open(str(config), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump(template, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print(json.dumps({'config': str(config), 'env_file': str(env), 'network_called': False,
                      'next': '在本地填写 Key、确认模型 ID，之后运行 debate.py doctor'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
