# syntax=docker/dockerfile:1
# MergeX AI frontend. `dev` runs the Vite dev server for docker-compose;
# production builds are deployed as static assets to Vercel.
ARG NODE_VERSION=22-alpine

FROM node:${NODE_VERSION} AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# `npm ci` when a lockfile exists, otherwise fall back to a plain install.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

FROM deps AS dev
WORKDIR /app
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM deps AS build
WORKDIR /app
COPY . .
RUN npm run build

# Static preview of the production bundle (Vercel is the real target).
FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY --from=build /app/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
