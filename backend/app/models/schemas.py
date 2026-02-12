# -*- coding: utf-8 -*-
"""API 请求/响应模型"""
from pydantic import BaseModel, Field


class ConvertResponse(BaseModel):
    """转换任务响应"""
    job_id: str = Field(..., description="任务 ID")
    status: str = Field(..., description="pending | converting | publishing | done | error")
    progress: int = Field(0, description="转换进度 0-100")
    message: str | None = Field(None, description="状态说明或错误信息")
    # 转换产物
    dxf_path: str | None = None
    gpkg_path: str | None = None
    layer_name: str | None = None
    # 前端可用的切片地址
    mvt_url: str | None = Field(None, description="MVT 矢量切片 URL")
    raster_url: str | None = Field(None, description="XYZ 栅格切片 URL")
    wmts_url: str | None = Field(None, description="WMTS Capabilities URL")
    # 图层边界 [minx, miny, maxx, maxy] EPSG:4326
    bbox: list[float] | None = Field(None, description="图层边界 [minx, miny, maxx, maxy] EPSG:4326")
