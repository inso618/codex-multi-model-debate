import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def test_setup_private_portable_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'private' / 'providers.json'
            command = [sys.executable, str(SKILL / 'scripts/setup.py'), '--config', str(config)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            report = json.loads(first.stdout)
            self.assertFalse(report['network_called'])
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertEqual((config.parent / 'keys.env').stat().st_mode & 0o777, 0o600)
            old = config.read_bytes()
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(config.read_bytes(), old)
            env = {**os.environ, 'DEBATE_CONFIG': str(config)}
            code = 'import debate; print(debate.DEFAULT_CONFIG)'
            found = subprocess.check_output([sys.executable, '-c', code], cwd=SKILL / 'scripts', env=env, text=True)
            self.assertEqual(found.strip(), str(config))

    def test_insecure_existing_key_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / 'keys.env'
            env.write_text('EXAMPLE_KEY=local-value\n')
            env.chmod(0o644)
            config = Path(tmp) / 'providers.json'
            result = subprocess.run([sys.executable, str(SKILL / 'scripts/setup.py'), '--config', str(config)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(config.exists())
            self.assertEqual(env.read_text(), 'EXAMPLE_KEY=local-value\n')


if __name__ == '__main__':
    unittest.main()
