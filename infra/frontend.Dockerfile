FROM node:24-alpine AS build
WORKDIR /workspace
COPY package.json package-lock.json tsconfig.base.json ./
COPY apps/admin/package.json apps/admin/package.json
COPY apps/client/package.json apps/client/package.json
COPY packages/contracts/package.json packages/contracts/package.json
RUN npm ci
COPY apps ./apps
COPY packages ./packages
ARG APP=admin
ARG ADMIN_PUBLIC_URL=http://127.0.0.1:5173
RUN VITE_DATA_MODE=api VITE_API_BASE_URL=/api VITE_WS_URL= VITE_ADMIN_URL=${ADMIN_PUBLIC_URL} npm run build --workspace @mood/${APP}
RUN cp -r apps/${APP}/dist /site

FROM nginx:stable-alpine
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /site /usr/share/nginx/html
EXPOSE 80
