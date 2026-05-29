# LibreDWG 后端部署说明

这个仓库当前保留后端服务和 `csrap_geoserver`，用于把 DWG 图纸转换成 GeoPackage，并发布到 GeoServer。前端由你单独打包部署，不包含在这份 tar 流程里。

如果你每次只想看一份文档，请直接看 [DEPLOY_README.md](/D:/project/LibreDWG/DEPLOY_README.md)。
那份文档是当前部署流程的唯一标准入口。

## 目录结构

```text
LibreDWG/
├── backend/
├── frontend/
├── geoserver_docker/
├── docker-compose.yml
├── docker-compose.offline.yml
├── README.md
└── DEPLOY_README.md
```

## Docker 方案

仓库根目录提供两份 compose：

- `docker-compose.yml`：适合有网机器，直接本地构建后端和 GeoServer 镜像
- `docker-compose.offline.yml`：适合离线服务器，直接使用 `docker load` 导入的镜像

## 联网机器上的构建与导出

在一台能联网的机器上执行：

```powershell
docker compose build backend csrap_geoserver
docker save -o libredwg-images.tar libredwg-backend:latest libredwg-geoserver:2.28.2
tar -czf libredwg-source.tar.gz --exclude='backend/data' --exclude='backend/data/*' backend geoserver_docker docker-compose.yml docker-compose.offline.yml README.md DEPLOY_README.md
```

生成两个文件：

- `libredwg-images.tar`
- `libredwg-source.tar.gz`

## 离线服务器上的启动

把上面的两个文件传到 Linux 服务器后，执行：

```bash
tar -xzf libredwg-source.tar.gz
docker load -i libredwg-images.tar
docker-compose -f docker-compose.offline.yml up -d
```

标准启动顺序也是：

```bash
cd /root/libredwg
docker-compose -f docker-compose.offline.yml down --remove-orphans
docker load -i libredwg-images.tar
docker-compose -f docker-compose.offline.yml up -d
docker-compose -f docker-compose.offline.yml ps
```

## 访问地址

- 后端 API：`http://<服务器IP>:19010/docs`
- GeoServer：`http://<服务器IP>:19080/geoserver`

前端请单独部署到你自己的静态站点或 nginx，挂载到例如 `/dwgupload/`。

## 后端与 GeoServer 的连接

后端在容器内部通过下面的地址访问 GeoServer：

- `APP_GEOSERVER_URL=http://csrap_geoserver:8080/geoserver`
- `APP_GEOSERVER_PUBLIC_URL=/csrap_geoserver`

这表示：

- 后端容器在 Docker 网络里直连 `csrap_geoserver`
- 对外返回给调用方的资源前缀仍然是 `/csrap_geoserver`

## 备注

- 离线服务器不要执行 `docker compose up -d --build`
- 离线服务器只负责 `docker load` 和 `docker-compose -f docker-compose.offline.yml up -d`
- 如果你想重新构建镜像，请在有网机器上执行 `docker compose build backend csrap_geoserver`
