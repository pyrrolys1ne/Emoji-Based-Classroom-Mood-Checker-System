import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('..', import.meta.url));
const venv = path.join(
  root,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
);
const python = process.env.MOOD_TEST_PYTHON || (existsSync(venv) ? venv : 'python');
const result = spawnSync(python, ['scripts/test_system.py', ...process.argv.slice(2)], {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
});
if (result.error) console.error('无法启动验收，请安装 Python 及后端开发、AI 基础依赖。');
process.exit(result.status ?? 1);
