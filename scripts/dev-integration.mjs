import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = path.join(
  root,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
);
if (!existsSync(python)) {
  console.error(
    '请先创建 .venv 并安装 services/integration/requirements.txt 与 services/ai/requirements.txt。',
  );
  process.exit(1);
}
for (const port of [8010, 8011, 5175]) {
  await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', () =>
      reject(new Error(`本机端口 ${port} 已占用，请先关闭此前的联调进程。`)),
    );
    server.listen(port, '127.0.0.1', () => server.close(resolve));
  });
}
const env = {
  ...process.env,
  PYTHONIOENCODING: 'utf-8',
  MOOD_INTEGRATION: '1',
  MOOD_AI_SERVICE_TOKEN: randomBytes(32).toString('hex'),
  AI_CONTROL_TOKEN: randomBytes(32).toString('hex'),
  AI_CONTROL_URL: 'http://127.0.0.1:8011',
  AI_BACKEND_URL: 'http://127.0.0.1:8010',
  MOOD_API_TARGET: 'http://127.0.0.1:8010',
  VITE_DATA_MODE: 'integration',
};
env.AI_SERVICE_TOKEN = env.MOOD_AI_SERVICE_TOKEN;
const commands = [
  [
    python,
    [
      '-m',
      'uvicorn',
      'integration_app.main:app',
      '--app-dir',
      'services/integration',
      '--host',
      '127.0.0.1',
      '--port',
      '8010',
    ],
  ],
  [
    process.env.AI_PYTHON_EXECUTABLE || python,
    [
      '-m',
      'uvicorn',
      'app.main:app',
      '--app-dir',
      'services/ai',
      '--host',
      '127.0.0.1',
      '--port',
      '8011',
    ],
  ],
  [
    process.execPath,
    [
      'node_modules/vite/bin/vite.js',
      'apps/admin',
      '--host',
      '127.0.0.1',
      '--port',
      '5175',
      '--strictPort',
    ],
  ],
];
const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (!child.pid || child.exitCode !== null) continue;
    if (process.platform === 'win32')
      spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], {
        stdio: 'ignore',
        windowsHide: true,
      });
    else child.kill('SIGTERM');
  }
  setTimeout(() => process.exit(code), 600).unref();
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
for (const [command, args] of commands) {
  const child = spawn(command, args, { cwd: root, env, stdio: 'inherit', windowsHide: true });
  children.push(child);
  child.on('error', (error) => {
    console.error(error.message);
    stop(1);
  });
  child.on('exit', (code) => {
    if (!stopping) stop(code ?? 1);
  });
}
console.log('\n本地联调：http://127.0.0.1:5175');
console.log('合成账号：admin 或 teacher，密码 integration-only。请勿用于正式环境。');
console.log('AI 入库和控制令牌仅通过进程环境共享，不发送到浏览器。Ctrl+C 停止全部联调进程。\n');
