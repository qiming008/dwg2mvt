# -*- coding: utf-8 -*-
"""DWG 转切片后端：上传 → LibreDWG → GDAL → GeoServer"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

app = FastAPI(
    title="DWG 转切片 API",
    description="上传 DWG，经 LibreDWG→DXF、GDAL→GeoPackage，发布为 GeoServer MVT/WMTS",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
async def root():
    return {"service": "dwg-to-tiles", "docs": "/docs"}
