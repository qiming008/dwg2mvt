# -*- coding: utf-8 -*-
"""DWG 转切片后端：上传 → LibreDWG → GDAL → GeoServer"""
import logging

from fastapi import FastAPI
from fastapi import HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import dict_router, router

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
app.include_router(dict_router)

logger = logging.getLogger(__name__)


@app.exception_handler(HTTPException)
async def log_http_exception(request: Request, exc: HTTPException):
    if exc.status_code == 400 and exc.detail == "There was an error parsing the body":
        logger.error(
            "Body parsing failed for %s %s: cause=%r",
            request.method,
            request.url.path,
            exc.__cause__,
        )
    return await http_exception_handler(request, exc)


@app.exception_handler(StarletteHTTPException)
async def log_starlette_http_exception(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 400 and exc.detail == "There was an error parsing the body":
        logger.error(
            "Starlette body parsing failed for %s %s: cause=%r type=%s",
            request.method,
            request.url.path,
            exc.__cause__,
            type(exc).__name__,
        )
    return await http_exception_handler(request, exc)


@app.get("/")
async def root():
    return {"service": "dwg-to-tiles", "docs": "/docs"}
