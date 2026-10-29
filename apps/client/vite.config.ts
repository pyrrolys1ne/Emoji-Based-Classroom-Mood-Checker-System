import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), 'VITE_');
  return {
    plugins: [react()],
    server: { proxy: { '/api': env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000' } },
  };
});
