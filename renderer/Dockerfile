# Renderer image for the situated-being simulation (BRIEF §6).
# Node base for the Vite dev server; docker-compose bind-mounts ./renderer over
# /app for live edits, so this image just needs the toolchain + deps installed.
FROM node:22-slim

WORKDIR /app

# Install dependencies first so this layer caches across app-code changes.
COPY package.json package-lock.json* ./
RUN npm install

# Copy the app. At runtime docker-compose bind-mounts ./renderer over /app (with
# an anonymous volume keeping /app/node_modules); this COPY keeps the image
# runnable on its own.
COPY . .

EXPOSE 5173

# Compose overrides this with `npm run dev -- --host 0.0.0.0`.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
