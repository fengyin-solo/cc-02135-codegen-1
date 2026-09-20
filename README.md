## How to Run

### Docker 启动（推荐）

```bash
# 构建并启动所有服务
docker-compose up --build -d

# 查看运行状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

启动后访问：
- 前端：http://localhost:8081
- 后端API：http://localhost:8636

### 本地启动

**后端：**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

**前端：**
直接用浏览器打开 `frontend/index.html`，或使用任意静态服务器：
```bash
cd frontend
python -m http.server 8081
```

## Services

| 服务 | 端口 | 说明 |
|------|------|------|
| frontend | 8081 | Nginx静态文件服务 + API代理 |
| backend | 8636 | Flask API服务 |

## 测试账号

| 用户名 | 密码 |
|--------|------|
| admin | admin123 |
| user | user123 |
| test | test123 |

## 运行测试

```bash
cd backend
pip install -r requirements.txt
pytest -v
```

## 题目内容

做一个下载网站，要求：
- 有加载动画
- 有上传按钮
- 点击下载时进行身份验证
- 验证完成后自动跳转下载
- 使用Python后端
- 前端端口：8081
- 后端端口：8636
- 支持Docker部署（ARM和X86跨平台）

---

## 项目介绍

做一个下载网站要有加载动画和上传按钮并且点击下载的时候会有身份验证的网页完成后自动跳转要用Python制作完成后放在文件夹中并且搭建服务器

### 功能特性

- 📤 文件上传
- 📥 文件下载（需身份验证）
- 👁️ 文件预览与元数据（内容摘要、文件类型、创建时间、可用操作、断点续读）
- 🔗 分享链接协作
- 🔐 用户身份验证
- ⏳ 加载动画效果
- 🐳 Docker一键部署

### 文件上传安全策略

项目采用扩展名黑名单机制，禁止上传以下类型的文件：

`exe, sh, bat, cmd, ps1, py, php, jsp, cgi, pl`

为什么用黑名单而不是白名单？
- 白名单需要预先列出所有允许的格式，每次有新格式都要手动添加，维护成本高
- 作为下载站，用户上传的文件类型多样且不可预测，白名单容易漏掉合法格式
- 黑名单只需拦截少量危险的可执行文件类型（如脚本、二进制程序），防止服务器被上传恶意代码利用
- 配合文件大小限制（默认50MB），已经能满足基本的安全需求

### 技术栈

- 前端：HTML + CSS + JavaScript
- 后端：Python Flask
- 部署：Docker + Nginx
