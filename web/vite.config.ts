import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Invariante 14b: todo serviço publica em `127.0.0.1`, nunca em `0.0.0.0`.
 *
 * Não basta o `docker-compose.yml`. Um `vite dev` publica em localhost por default,
 * mas `vite preview` e qualquer `--host` acidental furam isso — então o host fica
 * escrito aqui, no arquivo, que é onde alguém o mudaria.
 *
 * O proxy existe para haver **uma origem só** em desenvolvimento: sem ele o
 * WebSocket sairia para outra porta e o navegador trataria tudo como cross-origin.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true,
        // Sem isto o WebSocket não passa pelo dev server.
        ws: true,
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
