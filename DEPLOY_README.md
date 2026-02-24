# Windows 服务器部署指南

## 1. 环境准备
1. **Python**: 安装 Python 3.11 或更高版本，务必勾选 "Add Python to PATH"。
2. **GeoServer**: 确保 GeoServer 已安装并运行（默认端口 8080）。
3. **依赖库**: 
   - 本项目自带 `tools` 目录包含了 GDAL 和 LibreDWG，无需单独安装。
   - 首次运行前，请先执行一次 `start.bat` 以自动创建虚拟环境并安装 Python 依赖。

## 2. 配置文件 (.env)
在 `backend` 目录下，复制 `.env.example` 为 `.env`，并修改以下关键配置：

```ini
# GeoServer 内部访问地址（后端服务用）
APP_GEOSERVER_URL=http://localhost:8080/geoserver

# GeoServer 公网访问地址（前端浏览器用）
# 如果你有域名，填 http://your-domain.com/geoserver
# 如果是 IP 访问，填 http://192.168.x.x:8080/geoserver
APP_GEOSERVER_PUBLIC_URL=http://<服务器IP或域名>:8080/geoserver

# 如果 GeoServer 密码修改过，请同步修改
APP_GEOSERVER_USER=admin
APP_GEOSERVER_PASSWORD=geoserver
```

## 3. 启动服务
- **首次运行**: 双击 `start.bat`，它会自动安装依赖并启动开发服务器。确认无误后关闭。
- **生产环境启动**: 双击 `start_prod.bat`（新创建的脚本）。
  - 该脚本会以多进程模式运行，性能更好。
  - 默认监听 `0.0.0.0:8000`。

## 4. 域名与端口配置 (推荐使用 Nginx 或 IIS)
虽然可以通过修改 `start_prod.bat` 直接监听 80 端口，但推荐使用 Nginx 或 IIS 进行反向代理，这样更安全且方便管理 SSL 证书。

### Nginx 配置示例
假设你的域名是 `dwg.example.com`：

```nginx
server {
    listen 80;
    server_name dwg.example.com;

    # 前端静态文件 (需先执行 npm run build)
    location / {
        root D:/project/LibreDWG/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # GeoServer 代理 (可选，如果不直接暴露 8080)
    location /geoserver/ {
        proxy_pass http://127.0.0.1:8080/geoserver/;
        proxy_set_header Host $host;
    }
}
```

### 常见问题
1. **防火墙**: 确保服务器防火墙开放了 8000 端口（如果直接访问）或 80/443 端口（如果用 Nginx）。
2. **GDAL 错误**: 如果遇到 DLL 缺失错误，请安装 `VC_redist.x64.exe` (Visual C++ Redistributable)。
