# -*- coding: utf-8 -*-
"""应用配置：路径、GeoServer、坐标系等"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """从环境变量读取配置"""
    # 工作目录：上传与转换产物存放
    work_dir: Path = Path("./data")
    # LibreDWG 可执行文件（系统 PATH 或绝对路径）
    dwg2dxf_cmd: str = str(Path(__file__).resolve().parent.parent / "tools" / "dwg2dxf.exe")
    # GDAL ogr2ogr（系统 PATH）
    ogr2ogr_cmd: str = str(Path(__file__).resolve().parent.parent / "tools" / "gdal" / "bin" / "gdal" / "apps" / "ogr2ogr.exe")
    # 输出坐标系（Web 地图常用）
    target_srs: str = "EPSG:3857"
    # GeoServer
    geoserver_url: str = "http://localhost:8080/geoserver"
    geoserver_user: str = "admin"
    geoserver_password: str = "geoserver"
    geoserver_workspace: str = "dwg"
    # 前端可访问的 GeoServer 基础 URL（若与后端同域可一致）
    geoserver_public_url: str | None = None

    class Config:
        env_prefix = "APP_"
        env_file = ".env"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.work_dir = Path(self.work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        if self.geoserver_public_url is None:
            self.geoserver_public_url = self.geoserver_url


settings = Settings()
