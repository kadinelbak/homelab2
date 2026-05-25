FROM node:18-alpine AS client-build
WORKDIR /app/client
COPY upstream/client/package*.json ./
RUN npm install --legacy-peer-deps
COPY upstream/client/ ./
RUN NODE_OPTIONS=--openssl-legacy-provider npm run build

FROM node:18-alpine
WORKDIR /app/server
COPY upstream/server/package*.json ./
RUN npm install --omit=dev
COPY upstream/server/ ./
COPY --from=client-build /app/client/build ./public
ENV PORT=8000
EXPOSE 8000
CMD ["node", "server.js"]
