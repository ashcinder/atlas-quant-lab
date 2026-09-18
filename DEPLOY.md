# Atlas Quant - 一键部署指南

## 快速开始

### 构建并运行 (推荐)

```bash
cd /path/to/atlas-quant
./deploy/run.sh
```

### 或手动构建和运行

```bash
# 构建
docker build -t atlas-quant .

# 运行
docker run -d --name atlas-quant -p 8080:8080 atlas-quant
```

## 访问

- **应用地址**: http://localhost:8080
- **API 文档**: http://localhost:8080/api/docs

## 环境变量 (可选)

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ATLAS_ALLOWED_ORIGINS` | `http://localhost:8080` | 允许的请求来源 |
| `ATLAS_ALLOW_REGISTRATION` | `true` | 是否允许新用户注册 |
| `ATLAS_SESSION_SECRET` | (自动生成) | 会话密钥 (建议设置 32+ 字符) |

### 示例：带环境变量运行

```bash
docker run -d --name atlas-quant \
  -p 8080:8080 \
  -e ATLAS_ALLOWED_ORIGINS=http://your-domain.com \
  -e ATLAS_SESSION_SECRET=your-secret-key-here \
  atlas-quant
```

## 常用命令

```bash
# 查看日志
docker logs -f atlas-quant

# 停止
docker stop atlas-quant

# 启动
docker start atlas-quant

# 完全删除
docker rm -f atlas-quant
```

## 包含组件

- **Frontend**: React + Vite (Nginx served)
- **Backend**: FastAPI (Python 3.14)
- **Supervisor**: Ethereum RPC 节点 (端口 42515)
- **ZKVM**: RISC Zero 零知识证明虚拟机

## 数据持久化

数据存储在容器内的 `/app/backend/.data` 目录，包括：
- SQLite 数据库
- 私钥和加密材料
- 零知识证明收据

如需持久化数据，请挂载卷：

```bash
docker run -d --name atlas-quant \
  -p 8080:8080 \
  -v atlas-data:/app/backend/.data \
  atlas-quant
```

---

## 如何分享给其他人

### 方式一：打包项目目录（离线传输）

**你做：**
```bash
# 在项目根目录执行
tar --exclude='.git' \
    --exclude='node_modules' \
    --exclude='frontend/node_modules' \
    --exclude='backend/.venv' \
    --exclude='strategy/zkvm/target' \
    -czvf atlas-quant.tar.gz .

# 然后发送这两个文件给对方：
# 1. atlas-quant.tar.gz（项目代码）
# 2. DEPLOY.md（部署说明）
```

**对方做：**
```bash
# 1. 解压
tar -xzvf atlas-quant.tar.gz

# 2. 构建并运行
cd atlas-quant  # 如果解压到了子目录
./deploy/run.sh
```

---

### 方式二：推送到 Docker Hub（在线传输）

**你做：**
```bash
# 1. 登录 Docker Hub
docker login

# 2. 标记镜像
docker tag atlas-quant:latest your-username/atlas-quant:latest

# 3. 推送
docker push your-username/atlas-quant:latest
```

**对方做：**
```bash
# 只需一行命令
docker run -d --name atlas-quant -p 8080:8080 your-username/atlas-quant
```

---

### 方式三：导出镜像为文件（离线传输，适合内网）

**你做：**
```bash
# 1. 构建镜像
docker build -t atlas-quant .

# 2. 导出为 tar 文件
docker save atlas-quant:latest -o atlas-quant-image.tar

# 3. 发送 atlas-quant-image.tar 给对方
```

**对方做：**
```bash
# 1. 加载镜像
docker load -i atlas-quant-image.tar

# 2. 运行
docker run -d --name atlas-quant -p 8080:8080 atlas-quant
```

---

## 推荐分享方式

| 场景 | 推荐方式 |
|------|----------|
| 内网/离线传输 | 方式一（tar.gz 包） |
| 公开/在线分享 | 方式二（Docker Hub） |
| 大团队/内网 | 方式三（镜像 tar 文件） |
