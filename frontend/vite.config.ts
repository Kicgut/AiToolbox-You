import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  base: '/static/workbench/',
  build: {
    outDir: '../app/static/workbench',
    emptyOutDir: true
  }
});

