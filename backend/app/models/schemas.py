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
    mine_code: str | None = None
    seam_code: str | None = None
    seam_label: str | None = None
    belt_code: str | None = None
    coordinate_system: str | None = None
    # 前端可用的切片地址
    mvt_url: str | None = Field(None, description="MVT 矢量切片 URL")
    raster_url: str | None = Field(None, description="XYZ 栅格切片 URL")
    wmts_url: str | None = Field(None, description="WMTS Capabilities URL")
    metadata_url: str | None = Field(None, description="Layer metadata JSON URL")
    # 图层边界 [minx, miny, maxx, maxy] EPSG:4326
    bbox: list[float] | None = Field(None, description="图层边界 [minx, miny, maxx, maxy] EPSG:4326")
    view_bbox: list[float] | None = Field(None, description="默认视角边界 [minx, miny, maxx, maxy] EPSG:4326")
    created_at: float | None = Field(None, description="创建时间戳")


class DeleteJobResponse(BaseModel):
    """删除任务响应"""
    ok: bool = Field(..., description="是否删除成功")
    job_id: str = Field(..., description="任务 ID")
    layer_name: str | None = Field(None, description="图层名称")
    store_name: str | None = Field(None, description="GeoServer datastore 名称")
    message: str | None = Field(None, description="删除结果说明")
