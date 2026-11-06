FROM oven/bun:1.4 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY . .
RUN bun run build

FROM oven/bun:1.4-slim
WORKDIR /app/dist
COPY --from=build /app/dist ./
ENV NODE_ENV=production PORT=3000
USER 1000:1000
EXPOSE 3000
# Bundled asset paths resolve from the working directory.
CMD ["bun", "server.js"]
