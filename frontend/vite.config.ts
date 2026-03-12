import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api/vods': {
        target: resolve(__dirname, '../../state/vods.json'),
        changeOrigin: true,
        rewrite: () => '/vods.json',
      },
      '/transcripts': {
        target: resolve(__dirname, '../../transcripts'),
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/transcripts/, ''),
      },
    },
  },
})