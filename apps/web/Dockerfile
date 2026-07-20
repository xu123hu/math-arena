# Math Arena Web - Dockerfile
FROM node:20-alpine

WORKDIR /app

# 安装 pnpm
RUN npm install -g pnpm@9

# 安装依赖
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 5173

# 启动命令
CMD ["pnpm", "dev", "--host"]
