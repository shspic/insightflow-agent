FROM node:20-alpine AS development

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM development AS build
ARG VITE_API_BASE_URL=
ARG VITE_APP_VERSION=production
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_APP_VERSION=${VITE_APP_VERSION}
RUN npm run build

FROM nginx:1.27-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY deploy/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf
COPY deploy/nginx/snippets /etc/nginx/snippets

EXPOSE 80 443
STOPSIGNAL SIGQUIT
CMD ["nginx", "-g", "daemon off;"]
