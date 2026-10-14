# Stage 1: Build React App
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Behind the platform gateway: UI at /designer/, API at /designer/api/v1
ARG VITE_API_BASE_URL=/designer/api/v1
ARG VITE_BASE=/designer/
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_BASE=$VITE_BASE
ENV FRONTEND_PORT=3232

RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3232

CMD ["nginx", "-g", "daemon off;"]

