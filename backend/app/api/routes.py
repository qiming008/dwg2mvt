# -*- coding: utf-8 -*-
"""上传 DWG、转换、发布、查询状态"""
import hashlib
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.models.schemas import ConvertResponse
from app.services import conversion
from app.services import geoserver_client as gs

router = APIRouter(prefix="/api", tags=["dwg"])

# 内存中的任务状态（生产可用 Redis/DB 替代）
_jobs: dict[str, dict] = {}


def _job_dir(job_id: str) -> Path:
    return settings.work_dir / "jobs" / job_id


def process_conversion_task(job_id: str, dwg_path: Path, job_dir: Path, original_filename: str):
    """后台处理转换任务"""
    def update_progress(percent: int, msg: str):
        if job_id in _jobs:
            _jobs[job_id]["progress"] = percent
            _jobs[job_id]["message"] = msg

    try:
        # 1. DWG -> DXF -> GPKG
        # 此时已在线程池中运行（由 BackgroundTasks 管理），可直接调用同步函数
        ok, gpkg_path, err = conversion.convert_dwg_to_gpkg(
            dwg_path, 
            job_dir, 
            progress_callback=update_progress
        )
        
        if not ok:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["message"] = err
            _jobs[job_id]["progress"] = 0
            return

        dxf_path = job_dir / f"{dwg_path.stem}.dxf"
        _jobs[job_id]["dxf_path"] = str(dxf_path)
        _jobs[job_id]["gpkg_path"] = str(gpkg_path)
        _jobs[job_id]["status"] = "publishing"
        _jobs[job_id]["message"] = "正在发布到 GeoServer"
        _jobs[job_id]["progress"] = 95

        # Get bbox
        ok_bbox, bbox = conversion.get_gpkg_bbox(gpkg_path)
        if ok_bbox:
            _jobs[job_id]["bbox"] = bbox

        # 2. 发布到 GeoServer
        store_name = f"dwg_{job_id}"
        # Use ASCII-only layer name to avoid GeoServer GWC REST API encoding mismatch errors (400)
        # caused by non-ASCII characters in filenames (e.g. Chinese)
        layer_name = f"layer_{job_id}"
        
        ok_ws, _ = gs.ensure_workspace()
        if ok_ws:
            # OGR2OGR produces "entities" table by default for DXF
            ok_pub, pub_err = gs.publish_gpkg(gpkg_path, store_name, layer_name, native_layer_name="entities")
            if ok_pub:
                # Add improved raster style (Text, Color, Rotation)
                gs.add_raster_style_to_layer(layer_name)

                _jobs[job_id]["layer_name"] = layer_name
                _jobs[job_id]["mvt_url"] = gs.get_mvt_url(layer_name)
                _jobs[job_id]["raster_url"] = gs.get_raster_url_v2(layer_name)
                _jobs[job_id]["wmts_url"] = gs.get_wmts_capabilities_url()
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["message"] = "转换并发布完成"
                _jobs[job_id]["progress"] = 100
            else:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["message"] = f"GeoServer 发布失败: {pub_err}"
                _jobs[job_id]["progress"] = 0
        else:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["message"] = "GeoServer 未配置或不可用"
            _jobs[job_id]["progress"] = 0

    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["message"] = f"服务器错误: {str(e)}"
        _jobs[job_id]["progress"] = 0


def _job_response(job_id: str) -> ConvertResponse:
    # If job is in memory, return it
    if job_id in _jobs:
        j = _jobs[job_id]
        return ConvertResponse(
                job_id=job_id,
                status=j["status"],
                progress=j.get("progress", 0),
                message=j.get("message"),
                dxf_path=j.get("dxf_path"),
                gpkg_path=j.get("gpkg_path"),
                layer_name=j.get("layer_name"),
                mvt_url=j.get("mvt_url"),
                raster_url=j.get("raster_url"),
                wmts_url=j.get("wmts_url"),
                bbox=j.get("bbox"),
            )
    
    # If not in memory (e.g. after restart), try to reconstruct from disk
    job_dir = _job_dir(job_id)
    if job_dir.exists():
        # Find the DWG file to determine the stem
        dwg_files = list(job_dir.glob("*.dwg"))
        if dwg_files:
            dwg_path = dwg_files[0]
            stem = dwg_path.stem
            gpkg_path = job_dir / f"{stem}.gpkg"
            
            # Check if processing was successful (GPKG exists)
            status = "done" if gpkg_path.exists() else "error"
            message = "Loaded from disk"
            
            # Try to get MVT/WMTS if published
            layer_name = f"layer_{job_id}"
            # We assume it might be published if it exists
            # Ideally we'd check GeoServer, but for now:
            mvt_url = gs.get_mvt_url(layer_name)
            raster_url = gs.get_raster_url_v2(layer_name)
            wmts_url = gs.get_wmts_capabilities_url()
            
            # Try to get bbox
            bbox = None
            if gpkg_path.exists():
                ok, box = conversion.get_gpkg_bbox(gpkg_path)
                if ok:
                    bbox = box
            
            return ConvertResponse(
                job_id=job_id,
                status=status,
                progress=100 if status == "done" else 0,
                message=message,
                dxf_path=str(job_dir / f"{stem}.dxf"),
                gpkg_path=str(gpkg_path),
                layer_name=layer_name,
                mvt_url=mvt_url,
                raster_url=raster_url,
                wmts_url=wmts_url,
                bbox=bbox,
            )
            
    raise HTTPException(404, "任务不存在")


@router.get("/jobs", response_model=list[dict])
async def list_jobs():
    """获取所有已上传的任务列表"""
    jobs_list = []
    jobs_dir = settings.work_dir / "jobs"
    if not jobs_dir.exists():
        return []
        
    for job_dir in jobs_dir.iterdir():
        if job_dir.is_dir():
            job_id = job_dir.name
            # Find .dwg file to get original name
            dwg_files = list(job_dir.glob("*.dwg"))
            if dwg_files:
                # Prefer original filename stored in memory
                filename = _jobs.get(job_id, {}).get("original_filename", dwg_files[0].name)
                # Determine status
                gpkg_path = job_dir / f"{dwg_files[0].stem}.gpkg"
                status = "done" if gpkg_path.exists() else "error"
                if job_id in _jobs:
                    status = _jobs[job_id]["status"]
                
                # Get progress if available
                progress = _jobs.get(job_id, {}).get("progress", 0) if job_id in _jobs else (100 if status == "done" else 0)

                jobs_list.append({
                    "job_id": job_id,
                    "filename": filename,
                    "status": status,
                    "progress": progress,
                    "message": _jobs.get(job_id, {}).get("message", "") if job_id in _jobs else "",
                    "created_at": job_dir.stat().st_mtime
                })
    
    # Sort by creation time, newest first
    jobs_list.sort(key=lambda x: x["created_at"], reverse=True)
    return jobs_list


@router.post("/convert", response_model=ConvertResponse)
def upload_and_convert(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """上传 DWG 文件，执行 DWG→DXF→GPKG 并可选发布到 GeoServer，返回任务 ID 与状态"""
    if not file.filename or not file.filename.lower().endswith(".dwg"):
        raise HTTPException(400, "请上传 .dwg 文件")
    
    # Generate unique Job ID to force fresh processing and avoid cache
    job_id = uuid.uuid4().hex
    
    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Use original filename to satisfy overwrite-by-name requirement
    safe_filename = file.filename
    dwg_path = job_dir / safe_filename
    
    # If file exists, we are overwriting (re-processing)
    
    try:
        with dwg_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        _jobs[job_id] = {"status": "error", "message": str(e), "progress": 0}
        return _job_response(job_id)

    _jobs[job_id] = {
        "status": "converting",
        "message": "正在转换 DWG → DXF → GeoPackage",
        "progress": 0,
        "dxf_path": None,
        "gpkg_path": None,
        "layer_name": None,
        "mvt_url": None,
        "raster_url": None,
        "wmts_url": None,
        "original_filename": file.filename,
    }

    if background_tasks:
        background_tasks.add_task(process_conversion_task, job_id, dwg_path, job_dir, file.filename)
    else:
        # Fallback if no background tasks (should not happen in FastAPI app)
        process_conversion_task(job_id, dwg_path, job_dir, file.filename)

    return _job_response(job_id)


@router.get("/convert/{job_id}", response_model=ConvertResponse)
async def get_convert_status(job_id: str):
    """查询转换任务状态与结果 URL"""
    return _job_response(job_id)


@router.get("/status/{job_id}", response_model=ConvertResponse)
async def get_status(job_id: str):
    """查询任务状态"""
    return _job_response(job_id)


@router.get("/layers/{job_id}", response_model=list[dict])
async def get_job_layers(job_id: str):
    """获取指定任务的图层列表（包含名称和颜色）"""
    # 优先从内存任务记录获取路径
    gpkg_path = None
    if job_id in _jobs and _jobs[job_id].get("gpkg_path"):
        path_str = _jobs[job_id]["gpkg_path"]
        if path_str:
            gpkg_path = Path(path_str)
    
    # 如果内存中没有（例如重启后），尝试默认路径
    if not gpkg_path:
        job_dir = _job_dir(job_id)
        if job_dir.exists():
            # Find the DWG file to determine the stem
            dwg_files = list(job_dir.glob("*.dwg"))
            if dwg_files:
                gpkg_path = job_dir / f"{dwg_files[0].stem}.gpkg"
            
    if not gpkg_path or not gpkg_path.exists():
        raise HTTPException(404, "GeoPackage file not found")
            
    return conversion.get_gpkg_layers(gpkg_path)


@router.get("/convert/{job_id}/gpkg")
async def download_gpkg(job_id: str):
    """下载转换后的 GeoPackage 文件"""
    gpkg_path = None
    
    # Try memory first
    if job_id in _jobs:
        path_str = _jobs[job_id].get("gpkg_path")
        if path_str:
            gpkg_path = Path(path_str)
            
    # Try disk if not found
    if not gpkg_path:
        job_dir = _job_dir(job_id)
        if job_dir.exists():
            dwg_files = list(job_dir.glob("*.dwg"))
            if dwg_files:
                gpkg_path = job_dir / f"{dwg_files[0].stem}.gpkg"

    if not gpkg_path or not gpkg_path.exists():
        raise HTTPException(404, "GPKG 文件不存在")
        
    return FileResponse(gpkg_path, filename=gpkg_path.name, media_type="application/geopackage+sqlite3")
