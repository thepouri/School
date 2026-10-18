# Multi-stage production build for React 19 Single-Page Application
# Stage 1: Build static assets using Node.js
FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies first for efficient layer caching
COPY package*.json ./
RUN npm ci

# Copy application source code and compile production assets
COPY . .
RUN npm run build

# Stage 2: Serve static assets via Nginx Alpine reverse proxy
FROM nginx:1.27-alpine AS runner

# Remove default nginx welcome site
RUN rm -rf /etc/nginx/conf.d/default.conf /usr/share/nginx/html/*

# Copy custom Nginx configuration with gzip, caching, and reverse proxy rules
COPY nginx.conf /etc/nginx/nginx.conf

# Copy compiled static assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

STOPSIGNAL SIGQUIT

CMD ["nginx", "-g", "daemon off;"]
