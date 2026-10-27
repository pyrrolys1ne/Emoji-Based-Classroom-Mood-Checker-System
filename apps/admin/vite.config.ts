import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const target = env.MOOD_API_TARGET ?? 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    server: { strictPort: true, proxy: { '/api': target, '/ws': { target, ws: true } } },
  };
});
