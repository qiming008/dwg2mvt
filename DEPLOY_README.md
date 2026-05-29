# 前后端部署说明

这份说明对应当前这套离线部署方式。

- 后端使用生成的 `tar` 包部署
- 前端单独打包成 `cadView.zip`
- 后端放到服务器根目录下的 `/opt/libredwg`
- 前端放到服务器的 `/JYKJCLOUD/JY-MICRO-MAP`
- 前端的 `config` 文件夹也放在前端目录中
- 最后通过重载 `nginx` 生效
- 后端打包前请清空 `backend/data/jobs` 和 `backend/data/layer_metadata`，这些是开发和测试过程里的运行数据，不应该打进部署包

---

## 1. 目录约定

服务器上建议使用下面的目录：

```text
/opt/libredwg
/JYKJCLOUD/JY-MICRO-MAP
```


## 2. 后端部署

### 2.1 上传文件

把下面两个文件上传到服务器 `/opt/libredwg`：

- `libredwg-images.tar`
- `libredwg-source.tar.gz`

### 2.2 解压源码包

如果你要重新生成源码包，先确保 `backend/data/jobs` 和 `backend/data/layer_metadata` 已清空。

```bash
cd /opt/libredwg
tar -xzf libredwg-source.tar.gz
```

### 2.3 导入镜像

```bash
cd /opt/libredwg
docker load -i libredwg-images.tar
```

### 2.4 启动后端

```bash
cd /opt/libredwg
docker-compose -f docker-compose.offline.yml down --remove-orphans
docker-compose -f docker-compose.offline.yml up -d
docker-compose -f docker-compose.offline.yml ps
```

### 2.5 常用检查命令

```bash
docker-compose -f docker-compose.offline.yml logs --tail=200 backend
docker-compose -f docker-compose.offline.yml logs --tail=200 csrap_geoserver
```

### 2.6 后端访问地址

- 后端 API：`http://<服务器IP>:19010/docs`
- GeoServer：`http://<服务器IP>:19080/geoserver`

---

## 3. 前端部署

### 3.1 上传文件

把你打好的 `cadView.zip` 上传到服务器的：

```text
/JYKJCLOUD/JY-MICRO-MAP
```

### 3.2 解压前端

```bash
cd /JYKJCLOUD/JY-MICRO-MAP
unzip -o cadView.zip
```

解压后确认目录结构类似：

```text
/JYKJCLOUD/JY-MICRO-MAP/
├── cadView/
├── config/
└── 其他静态文件
```

### 3.3 前端 nginx 配置

前端站点建议指向 `cadView` 目录。

示例配置：

```nginx
server {
    listen 19001;
    server_name localhost;
    gzip_static on;
    gzip_http_version 1.0;
    root /JYKJCLOUD/JY-MICRO-MAP/cadView;

    index index.html;

    location / {
        root /JYKJCLOUD/JY-MICRO-MAP/cadView;
        try_files $uri $uri/ /index.html last;
        index index.html;
    }
}
```

如果你已经把 nginx 配置文件放进了 `config` 目录，就把对应的配置文件替换到服务器正在使用的位置。

---

## 4. 重载 nginx

如果前端是容器里的 nginx，执行：

```bash
docker exec -it jykjcloudx-front nginx -s reload
```

如果你是直接在宿主机上跑 nginx，就执行：

```bash
nginx -s reload
```

---

## 5. 标准更新流程

如果后面只更新后端，按这个顺序：

```bash
cd /opt/libredwg
docker-compose -f docker-compose.offline.yml down --remove-orphans
docker load -i libredwg-images.tar
tar -xzf libredwg-source.tar.gz
docker-compose -f docker-compose.offline.yml up -d
```

如果只更新前端，按这个顺序：

```bash
cd /JYKJCLOUD/JY-MICRO-MAP
unzip -o cadView.zip
docker exec -it jykjcloudx-front nginx -s reload
```

---


---

## 7. 注意事项

- 后端和前端更新前，先确认没有旧容器占着同样端口
- 如果出现 `port is already allocated`，先查清楚是不是旧容器还在
- 前端 `config` 文件夹不要漏掉
- 前端改完静态文件后，记得重载 nginx，不然不会生效
- 后端部署时不要在服务器上重新 `docker build`，直接用我导出的 `tar` 包

---

## 8. 备忘

这套项目的关键文件是：

- 后端镜像：`libredwg-images.tar`
- 后端源码包：`libredwg-source.tar.gz`
- 前端包：`cadView.zip`
- 前端站点目录：`/JYKJCLOUD/JY-MICRO-MAP`
- 后端部署目录：`/opt/libredwg`
