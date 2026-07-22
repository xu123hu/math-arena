# Math Arena Web - Dockerfile (monorepo)
# 构建上下文: 项目根目录 (docker compose 中 context: ..)

FROM node:20-alpine

WORKDIR /app

# 安装 pnpm
RUN npm install -g pnpm@9

# 复制 monorepo 根配置
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

# 复制共享协议包
COPY packages/protocol/package.json ./packages/protocol/

# 复制 Web 应用包描述
COPY apps/web/package.json ./apps/web/

# 安装依赖
RUN pnpm install

# 复制 Web 应用源码
COPY apps/web/ ./apps/web/

# 暴露端口
EXPOSE 5173

# 启动开发服务器
CMD ["pnpm", "--filter", "@math-arena/web", "dev", "--host"]
