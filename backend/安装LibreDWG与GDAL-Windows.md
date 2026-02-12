# Windows 环境下 LibreDWG 与 GDAL 安装指南

本项目依赖 **LibreDWG** (用于 DWG 转 DXF) 和 **GDAL** (用于 DXF 转 GeoPackage)。
为简化 Windows 下的配置，我们提供了一键配置脚本。

## 方案一：一键自动配置（推荐）

我们在 `backend` 目录下提供了一个 PowerShell 脚本，可自动下载并配置便携版工具。

### 1. 运行配置脚本
1.  进入 `backend` 目录。
2.  右键点击 `setup_libredwg.ps1`，选择 **“使用 PowerShell 运行”**。
    *   或者在 PowerShell 终端中运行：`.\setup_libredwg.ps1`
3.  脚本将会：
    *   自动从 GitHub 下载 LibreDWG Windows 版。
    *   解压到 `backend\tools\libredwg` 目录。
    *   自动更新 `.env` 配置文件中的路径。

### 2. GDAL 手动下载
由于 GDAL 及其依赖较为复杂，建议手动下载便携包：

1.  访问 [GISInternals Release 页面](https://www.gisinternals.com/release.php)。
2.  选择最新的稳定版本（例如 `release-1930-x64-gdal-3-8-4-mapserver-8-0-1`）。
3.  下载 **`...-gdal-x-x-x-mapserver-x-x-x.zip`** (Generic installer for core components)。
4.  将解压后的文件夹重命名为 `gdal`。
5.  将该文件夹放入 `backend\tools\` 目录下。
    *   确保文件结构为：`backend\tools\gdal\bin\ogr2ogr.exe`

### 3. 验证安装
直接运行 `backend\start.bat`，脚本会自动检测 `tools` 目录下的工具。如果看到以下日志，说明配置成功：
```
dwg2dxf: 已找到
ogr2ogr: 已找到
```

---

## 方案二：使用 OSGeo4W（高级用户）

如果您已经安装了 OSGeo4W：

1.  确保在 OSGeo4W 安装程序中选择了 `gdal` 和 `libredwg`（如果可用）。
2.  修改 `backend\.env` 文件，手动指定路径：
    ```env
    APP_DWG2DXF_CMD=C:\OSGeo4W\bin\dwg2dxf.exe
    APP_OGR2OGR_CMD=C:\OSGeo4W\bin\ogr2ogr.exe
    ```

## 方案三：完全手动安装

如果自动脚本无法使用，您可以手动下载并配置：

### 1. LibreDWG
1.  下载 [LibreDWG Windows Releases](https://github.com/LibreDWG/libredwg/releases) (`win64.zip`)。
2.  解压到 `backend\tools\libredwg`。
3.  确保存在 `backend\tools\libredwg\dwg2dxf.exe`。

### 2. GDAL
同方案一中的步骤 2，下载并解压到 `backend\tools\gdal`。
