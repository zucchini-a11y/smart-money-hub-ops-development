import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const root = path.resolve(import.meta.dirname);

export default defineConfig({
  base: '/_vayda_landing/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(root, 'src'),
      '@assets': path.resolve(root, '..', '..', 'attached_assets'),
    },
    dedupe: ['react', 'react-dom'],
  },
  root,
  build: {
    outDir: path.resolve(root, 'dist/landing'),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(root, 'landing.html'),
    },
  },
});
