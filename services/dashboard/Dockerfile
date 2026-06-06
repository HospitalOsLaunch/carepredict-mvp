FROM node:22.12.0-bookworm-slim

WORKDIR /app
COPY services/dashboard/package.json services/dashboard/package-lock.json /app/
RUN npm ci

COPY services/dashboard /app
CMD ["npm", "run", "dev"]
