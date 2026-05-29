# -*- coding: utf-8 -*-
"""Upload, convert, publish and query DWG/DXF jobs."""

import asyncio
import json
import re
import shutil
import uuid
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from app.config import settings
from app.models.schemas import ConvertResponse, DeleteJobResponse
from app.services.coordinate_systems import list_coordinate_system_options
from app.services import conversion
from app.services import geoserver_client as gs
from app.services.wmts_security import verify_wmts_request_uri

router = APIRouter(prefix="/api", tags=["dwg"])
dict_router = APIRouter(prefix="/jy-csp-gis", tags=["dict"])

_jobs: dict[str, dict] = {}
_preview_tasks: set[str] = set()
ORIGINAL_PREVIEW_VERSION = 12


def _job_dir(job_id: str) -> Path:
    return settings.work_dir / "jobs" / job_id


def _job_meta_path(job_dir: Path) -> Path:
    return job_dir / "job_meta.json"


def _original_preview_path(job_dir: Path) -> Path:
    return job_dir / "original_preview.svg"


def _original_preview_status_path(job_dir: Path) -> Path:
    return job_dir / "original_preview_status.json"


def _original_preview_url(job_id: str) -> str:
    return f"/csrap_mapapi/convert/{job_id}/original-preview/file?v={ORIGINAL_PREVIEW_VERSION}"


def _metadata_dir() -> Path:
    return settings.work_dir / "layer_metadata"


def _metadata_path(layer_name: str) -> Path:
    return _metadata_dir() / f"{_safe_code_part(layer_name)}.json"


def _load_job_meta(job_dir: Path) -> dict:
    meta_path = _job_meta_path(job_dir)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_job_meta(job_dir: Path, meta: dict) -> None:
    _job_meta_path(job_dir).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_preview_status(job_dir: Path) -> dict:
    status_path = _original_preview_status_path(job_dir)
    if not status_path.exists():
        return {}
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_preview_status(job_id: str, job_dir: Path, status: dict) -> dict:
    payload = {
        "status": status.get("status", "pending"),
        "url": status.get("url"),
        "message": status.get("message"),
        "updated_at": status.get("updated_at", time.time()),
        "preview_version": ORIGINAL_PREVIEW_VERSION,
    }
    _original_preview_status_path(job_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if job_id in _jobs:
        _jobs[job_id]["original_preview_status"] = payload
    return payload


def _get_preview_status(job_id: str) -> dict:
    job_dir = _job_dir(job_id)
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    preview_path = _original_preview_path(job_dir)
    saved = _load_preview_status(job_dir)
    if (
        preview_path.exists()
        and preview_path.stat().st_size > 0
        and saved.get("preview_version") == ORIGINAL_PREVIEW_VERSION
    ):
        return {
            "status": "ready",
            "url": _original_preview_url(job_id),
            "message": saved.get("message") or "原图预览已生成",
            "updated_at": saved.get("updated_at") or preview_path.stat().st_mtime,
        }

    status = saved.get("status")
    if status == "running" and job_id in _preview_tasks:
        return {
            "status": "running",
            "url": None,
            "message": saved.get("message") or "正在生成原图预览",
            "updated_at": saved.get("updated_at") or time.time(),
        }
    if status == "error":
        return {
            "status": "error",
            "url": None,
            "message": saved.get("message") or "原图预览生成失败",
            "updated_at": saved.get("updated_at") or time.time(),
        }

    return {
        "status": "pending",
        "url": None,
        "message": "原图预览尚未生成",
        "updated_at": saved.get("updated_at") or None,
    }


def _save_layer_manifest(job_dir: Path, layer_name: str, manifest: list[dict]) -> Path:
    metadata_dir = _metadata_dir()
    metadata_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = _metadata_path(layer_name)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2)
    manifest_path.write_text(payload, encoding="utf-8")
    (job_dir / "layer_metadata.json").write_text(payload, encoding="utf-8")
    return manifest_path


def _safe_code_part(value: str | None, default: str = "unknown") -> str:
    if not value:
        return default
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or default


def _job_names_from_meta(job_id: str, meta: dict, runtime_job: dict | None = None) -> tuple[str | None, str | None]:
    runtime_job = runtime_job or {}
    layer_name = runtime_job.get("layer_name") or meta.get("layer_name")
    store_name = runtime_job.get("store_name") or meta.get("store_name")

    safe_mine_code = _safe_code_part(runtime_job.get("mine_code") or meta.get("mine_code"))
    safe_seam_code = _safe_code_part(runtime_job.get("seam_code") or meta.get("seam_code"))

    if not layer_name:
        layer_name = f"layer_{safe_mine_code}_{safe_seam_code}"
    if not store_name:
        store_name = f"dwg_{safe_mine_code}_{safe_seam_code}_{job_id[:8]}"
    return layer_name, store_name


def _cleanup_previous_jobs_for_layer(current_job_id: str, layer_name: str) -> list[str]:
    """Remove older completed jobs that publish the same logical layer."""
    removed_jobs: list[str] = []
    jobs_dir = settings.work_dir / "jobs"
    if not jobs_dir.exists():
        return removed_jobs

    for job_dir in jobs_dir.iterdir():
        if not job_dir.is_dir() or job_dir.name == current_job_id:
            continue

        job_id = job_dir.name
        meta = _load_job_meta(job_dir)
        runtime_job = _jobs.get(job_id, {})
        candidate_layer_name, candidate_store_name = _job_names_from_meta(job_id, meta, runtime_job)
        if candidate_layer_name != layer_name:
            continue

        candidate_status = str(runtime_job.get("status") or meta.get("status") or "").lower()
        if candidate_status in {"converting", "publishing"}:
            continue

        try:
            if candidate_layer_name:
                gs.delete_published_layer(candidate_layer_name, candidate_store_name)
            manifest_path = _metadata_path(candidate_layer_name)
            if manifest_path.exists():
                manifest_path.unlink()
            shutil.rmtree(job_dir, ignore_errors=True)
            _jobs.pop(job_id, None)
            removed_jobs.append(job_id)
        except Exception:
            # Keep the new upload moving; cleanup is best-effort.
            continue

    return removed_jobs


def _parse_visible_layers(value: str | None) -> list[str] | None:
    if value is None:
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass

    return [part.strip() for part in raw.split(",") if part.strip()]


@dict_router.get("/api/v2.7/three/sysDict/list")
async def proxy_sys_dict_list(request: Request):
    """Proxy the dictionary service so the frontend can stay same-origin in Docker."""
    if not settings.dict_service_base_url:
        raise HTTPException(status_code=503, detail="Dictionary service is not configured")

    target = settings.dict_service_base_url.rstrip("/") + settings.dict_service_path

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            upstream = await client.get(target, params=dict(request.query_params))
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Dictionary service request failed: {exc}") from exc

    content_type = upstream.headers.get("content-type", "application/json")
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=content_type)


@router.get("/wmts/verify", include_in_schema=False)
async def verify_wmts_access(request: Request):
    """Verify WMTS access ticket before proxying tiles to GeoServer."""
    original_uri = request.headers.get("x-original-uri") or str(request.url)
    ok, message = verify_wmts_request_uri(original_uri)
    if not ok:
        raise HTTPException(status_code=403, detail=message)
    return Response(status_code=204)


def _job_source_file(job_dir: Path) -> Path | None:
    for pattern in ("*.dwg", "*.dxf"):
        files = sorted(job_dir.glob(pattern))
        if files:
            return files[0]
    return None


def _job_gpkg_file(job_id: str, job_dir: Path) -> Path | None:
    if job_id in _jobs:
        path_str = _jobs[job_id].get("gpkg_path")
        if path_str:
            gpkg_path = Path(path_str)
            if gpkg_path.exists():
                return gpkg_path

    source_file = _job_source_file(job_dir)
    if source_file:
        gpkg_path = job_dir / f"{source_file.stem}.gpkg"
        if gpkg_path.exists():
            return gpkg_path

    gpkg_files = sorted(job_dir.glob("*.gpkg"))
    return gpkg_files[0] if gpkg_files else None


def process_conversion_task(
    job_id: str,
    source_path: Path,
    job_dir: Path,
    original_filename: str,
    mine_code: str,
    coordinate_system: str,
    seam_code: str,
    seam_label: str | None,
    clean_mode: bool,
    visible_layers: list[str] | None,
    store_name: str,
):
    def update_progress(percent: int, msg: str):
        if job_id in _jobs:
            _jobs[job_id]["progress"] = percent
            _jobs[job_id]["message"] = msg

    try:
        ok, gpkg_path, err = conversion.convert_dwg_to_gpkg(
            source_path,
            job_dir,
            progress_callback=update_progress,
            coordinate_system_code=coordinate_system,
        )

        if not ok:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["message"] = err
            _jobs[job_id]["progress"] = 0
            return

        dxf_path = job_dir / f"{source_path.stem}.dxf"
        _jobs[job_id]["dxf_path"] = str(dxf_path)
        _jobs[job_id]["gpkg_path"] = str(gpkg_path)
        _jobs[job_id]["status"] = "publishing"
        _jobs[job_id]["message"] = "Publishing to GeoServer"
        _jobs[job_id]["progress"] = 95

        if clean_mode:
            update_progress(86, "Cleaning text and annotation layers")
            conversion.clean_gpkg_for_vector_preview(gpkg_path)

        conversion.apply_layer_visibility_override(gpkg_path, visible_layers)

        ok_bbox, bbox = conversion.get_gpkg_bbox(gpkg_path)
        if not ok_bbox or not bbox:
            try:
                robust = conversion.get_robust_bbox(gpkg_path)
                if robust:
                    min_x, max_x, min_y, max_y, *_ = robust
                    bbox = [min_x, min_y, max_x, max_y]
                    ok_bbox = True
            except Exception:
                pass
        if ok_bbox and bbox:
            _jobs[job_id]["bbox"] = bbox
        try:
            view_bbox = conversion.get_view_bbox(gpkg_path)
            if view_bbox:
                _jobs[job_id]["view_bbox"] = view_bbox
                meta = _load_job_meta(job_dir)
                meta["view_bbox"] = view_bbox
                _save_job_meta(job_dir, meta)
        except Exception as view_err:
            print(f"View bbox detection warning: {view_err}")

        safe_mine_code = _safe_code_part(mine_code)
        safe_seam_code = _safe_code_part(seam_code)
        layer_name = f"layer_{safe_mine_code}_{safe_seam_code}"

        _cleanup_previous_jobs_for_layer(job_id, layer_name)

        ok_ws, ws_err = gs.ensure_workspace()
        if ok_ws:
            ok_pub, pub_err = gs.publish_gpkg(gpkg_path, store_name, layer_name, native_layer_name="entities")
            if ok_pub:
                gs.add_raster_style_to_layer(layer_name)
                manifest = conversion.get_gpkg_monitor_manifest(gpkg_path)
                manifest_path = _save_layer_manifest(job_dir, layer_name, manifest)
                _jobs[job_id]["layer_name"] = layer_name
                _jobs[job_id]["store_name"] = store_name
                _jobs[job_id]["mvt_url"] = gs.get_mvt_url(layer_name)
                _jobs[job_id]["raster_url"] = gs.get_raster_url_v2(layer_name)
                _jobs[job_id]["wmts_url"] = gs.get_wmts_capabilities_url()
                _jobs[job_id]["metadata_url"] = f"/csrap_mapapi/layer-metadata/{layer_name}"
                _jobs[job_id]["metadata_path"] = str(manifest_path)
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["message"] = "Conversion and publish done"
                _jobs[job_id]["progress"] = 100
            else:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["message"] = f"GeoServer publish failed: {pub_err}"
                _jobs[job_id]["progress"] = 0
        else:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["message"] = f"GeoServer not configured or unavailable: {ws_err}"
            _jobs[job_id]["progress"] = 0

    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["message"] = f"Server error: {str(e)}"
        _jobs[job_id]["progress"] = 0


def _job_response(job_id: str) -> ConvertResponse:
    if job_id in _jobs:
        j = _jobs[job_id]
        layer_name = j.get("layer_name")
        mvt_url = j.get("mvt_url")
        raster_url = j.get("raster_url")
        wmts_url = j.get("wmts_url")
        view_bbox = j.get("view_bbox")
        if layer_name:
            mvt_url = gs.get_mvt_url(layer_name)
            raster_url = gs.get_raster_url_v2(layer_name)
            wmts_url = gs.get_wmts_capabilities_url()
            j["mvt_url"] = mvt_url
            j["raster_url"] = raster_url
            j["wmts_url"] = wmts_url
        return ConvertResponse(
            job_id=job_id,
            status=j["status"],
            progress=j.get("progress", 0),
            message=j.get("message"),
            dxf_path=j.get("dxf_path"),
            gpkg_path=j.get("gpkg_path"),
            layer_name=layer_name,
            belt_code=j.get("coordinate_system") or j.get("belt_code"),
            coordinate_system=j.get("coordinate_system") or j.get("belt_code"),
            mvt_url=mvt_url,
            raster_url=raster_url,
            wmts_url=wmts_url,
            metadata_url=j.get("metadata_url"),
            bbox=j.get("bbox"),
            view_bbox=view_bbox,
            mine_code=j.get("mine_code"),
            seam_code=j.get("seam_code"),
            seam_label=j.get("seam_label"),
            created_at=j.get("created_at"),
        )

    job_dir = _job_dir(job_id)
    if job_dir.exists():
        meta = _load_job_meta(job_dir)
        source_file = _job_source_file(job_dir)
        if source_file:
            stem = source_file.stem
            gpkg_path = job_dir / f"{stem}.gpkg"
            status = "done" if gpkg_path.exists() else "error"
            message = "Loaded from disk"

            safe_mine_code = _safe_code_part(meta.get("mine_code"))
            safe_seam_code = _safe_code_part(meta.get("seam_code"))
            layer_name = f"layer_{safe_mine_code}_{safe_seam_code}"
            mvt_url = gs.get_mvt_url(layer_name)
            raster_url = gs.get_raster_url_v2(layer_name)
            wmts_url = gs.get_wmts_capabilities_url()
            metadata_url = f"/csrap_mapapi/layer-metadata/{layer_name}"

            bbox = None
            view_bbox = None
            if gpkg_path.exists():
                ok, box = conversion.get_gpkg_bbox(gpkg_path)
                if ok:
                    bbox = box
                view_bbox = meta.get("view_bbox")

            return ConvertResponse(
                job_id=job_id,
                status=status,
                progress=100 if status == "done" else 0,
                message=message,
                dxf_path=str(job_dir / f"{stem}.dxf"),
                gpkg_path=str(gpkg_path),
                layer_name=layer_name,
                belt_code=meta.get("coordinate_system") or meta.get("belt_code"),
                coordinate_system=meta.get("coordinate_system") or meta.get("belt_code"),
                mvt_url=mvt_url,
                raster_url=raster_url,
                wmts_url=wmts_url,
                metadata_url=metadata_url,
                bbox=bbox,
                view_bbox=view_bbox,
                mine_code=meta.get("mine_code"),
                seam_code=meta.get("seam_code"),
                seam_label=meta.get("seam_label"),
                created_at=meta.get("created_at") or job_dir.stat().st_mtime,
            )

    raise HTTPException(404, "Job not found")


@router.get("/jobs", response_model=list[dict])
async def list_jobs():
    jobs_list = []
    jobs_dir = settings.work_dir / "jobs"
    if not jobs_dir.exists():
        return []

    for job_dir in jobs_dir.iterdir():
        if not job_dir.is_dir():
            continue

        job_id = job_dir.name
        meta = _load_job_meta(job_dir)
        source_file = _job_source_file(job_dir)
        if not source_file:
            continue

        filename = _jobs.get(job_id, {}).get("original_filename", meta.get("original_filename", source_file.name))
        gpkg_path = job_dir / f"{source_file.stem}.gpkg"
        status = "done" if gpkg_path.exists() else "error"
        if job_id in _jobs:
            status = _jobs[job_id]["status"]

        progress = _jobs.get(job_id, {}).get("progress", 0) if job_id in _jobs else (100 if status == "done" else 0)
        created_at = meta.get("created_at") or job_dir.stat().st_mtime

        jobs_list.append(
            {
                "job_id": job_id,
                "filename": filename,
                "mine_code": _jobs.get(job_id, {}).get("mine_code", meta.get("mine_code")),
                "coordinate_system": _jobs.get(job_id, {}).get("coordinate_system", meta.get("coordinate_system", meta.get("belt_code"))),
                "belt_code": _jobs.get(job_id, {}).get("coordinate_system", meta.get("coordinate_system", meta.get("belt_code"))),
                "seam_code": _jobs.get(job_id, {}).get("seam_code", meta.get("seam_code")),
                "seam_label": _jobs.get(job_id, {}).get("seam_label", meta.get("seam_label")),
                "status": status,
                "progress": progress,
                "message": _jobs.get(job_id, {}).get("message", "") if job_id in _jobs else "",
                "created_at": created_at,
            }
        )

    jobs_list.sort(key=lambda x: x["created_at"], reverse=True)
    return jobs_list


@router.post("/convert", response_model=ConvertResponse)
async def upload_and_convert(
    file: UploadFile = File(...),
    mine_code: str = Form(...),
    coordinateSystem: str = Form(...),
    seam_code: str = Form(...),
    seam_label: str | None = Form(None),
    clean_mode: bool = Form(True),
    visible_layers: str | None = Form(None),
):
    if not file.filename or not file.filename.lower().endswith((".dwg", ".dxf")):
        raise HTTPException(400, "Please upload a .dwg or .dxf file")

    coordinate_system_value = str(coordinateSystem).strip()
    if not coordinate_system_value:
        raise HTTPException(400, "Please select a coordinate system")

    job_id = uuid.uuid4().hex
    safe_mine_code = _safe_code_part(mine_code)
    safe_seam_code = _safe_code_part(seam_code)
    layer_name = f"layer_{safe_mine_code}_{safe_seam_code}"
    store_name = f"dwg_{safe_mine_code}_{safe_seam_code}_{job_id[:8]}"

    visible_layer_list = _parse_visible_layers(visible_layers)

    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = file.filename
    source_path = job_dir / safe_filename

    try:
        with source_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        _jobs[job_id] = {"status": "error", "message": str(e), "progress": 0}
        return _job_response(job_id)

    _save_job_meta(
        job_dir,
        {
            "job_id": job_id,
            "original_filename": file.filename,
            "created_at": time.time(),
            "mine_code": mine_code,
            "coordinate_system": coordinate_system_value,
            "belt_code": coordinate_system_value,
            "seam_code": seam_code,
            "seam_label": seam_label,
            "clean_mode": clean_mode,
            "visible_layers": visible_layer_list,
            "layer_name": layer_name,
            "store_name": store_name,
        },
    )

    _jobs[job_id] = {
        "status": "converting",
        "message": "Converting source file to GPKG",
        "progress": 0,
        "dxf_path": None,
        "gpkg_path": None,
        "layer_name": None,
        "mvt_url": None,
        "raster_url": None,
        "wmts_url": None,
        "original_filename": file.filename,
        "mine_code": mine_code,
        "coordinate_system": coordinate_system_value,
        "belt_code": coordinate_system_value,
        "seam_code": seam_code,
        "seam_label": seam_label,
        "clean_mode": clean_mode,
        "visible_layers": visible_layer_list,
        "layer_name": layer_name,
        "store_name": store_name,
    }

    async def _run_conversion_job() -> None:
        await asyncio.to_thread(
            process_conversion_task,
            job_id,
            source_path,
            job_dir,
            file.filename,
            mine_code,
            coordinate_system_value,
            seam_code,
            seam_label,
            clean_mode,
            visible_layer_list,
            store_name,
        )

    asyncio.create_task(_run_conversion_job())

    return _job_response(job_id)


@router.get("/convert/{job_id}", response_model=ConvertResponse)
async def get_convert_status(job_id: str):
    return _job_response(job_id)


@router.get("/status/{job_id}", response_model=ConvertResponse)
async def get_status(job_id: str):
    return _job_response(job_id)


@router.get("/layers/{job_id}", response_model=list[dict])
async def get_job_layers(job_id: str):
    gpkg_path = None
    if job_id in _jobs and _jobs[job_id].get("gpkg_path"):
        path_str = _jobs[job_id]["gpkg_path"]
        if path_str:
            gpkg_path = Path(path_str)

    if not gpkg_path:
        job_dir = _job_dir(job_id)
        if job_dir.exists():
            source_file = _job_source_file(job_dir)
            if source_file:
                gpkg_path = job_dir / f"{source_file.stem}.gpkg"

    if not gpkg_path or not gpkg_path.exists():
        raise HTTPException(404, "GeoPackage file not found")

    return conversion.get_gpkg_layers(gpkg_path)


@router.get("/layer-metadata/{layer_name}", response_model=list[dict])
async def get_layer_metadata(layer_name: str):
    manifest_path = _metadata_path(layer_name)
    if not manifest_path.exists():
        jobs_dir = settings.work_dir / "jobs"
        if jobs_dir.exists():
            for job_dir in jobs_dir.iterdir():
                if not job_dir.is_dir():
                    continue
                meta = _load_job_meta(job_dir)
                safe_mine_code = _safe_code_part(meta.get("mine_code"))
                safe_seam_code = _safe_code_part(meta.get("seam_code"))
                candidate_layer_name = f"layer_{safe_mine_code}_{safe_seam_code}"
                if candidate_layer_name != layer_name:
                    continue

                source_file = _job_source_file(job_dir)
                if not source_file:
                    continue
                gpkg_path = job_dir / f"{source_file.stem}.gpkg"
                if not gpkg_path.exists():
                    continue

                manifest = conversion.get_gpkg_monitor_manifest(gpkg_path)
                manifest_path = _save_layer_manifest(job_dir, layer_name, manifest)
                break

    if not manifest_path.exists():
        raise HTTPException(404, "Layer metadata not found")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, list):
            raise ValueError("Invalid layer metadata format")

        mvt_url = gs.get_mvt_url(layer_name)
        raster_url = gs.get_raster_url(layer_name)
        wmts_url = gs.get_wmts_capabilities_url()
        enriched_manifest: list[dict] = []
        for item in manifest:
            if not isinstance(item, dict):
                continue
            enriched_item = dict(item)
            enriched_item["mvt_url"] = mvt_url
            enriched_item["raster_url"] = raster_url
            enriched_item["wmts_url"] = wmts_url
            enriched_manifest.append(enriched_item)

        return enriched_manifest
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(500, f"Failed to read layer metadata: {e}")


@router.get("/coordinate-systems", response_model=list[dict])
async def get_coordinate_systems():
    return list_coordinate_system_options()


@router.get("/convert/{job_id}/gpkg")
async def download_gpkg(job_id: str):
    gpkg_path = None
    if job_id in _jobs:
        path_str = _jobs[job_id].get("gpkg_path")
        if path_str:
            gpkg_path = Path(path_str)

    if not gpkg_path:
        job_dir = _job_dir(job_id)
        if job_dir.exists():
            source_file = _job_source_file(job_dir)
            if source_file:
                gpkg_path = job_dir / f"{source_file.stem}.gpkg"

    if not gpkg_path or not gpkg_path.exists():
        raise HTTPException(404, "GPKG file not found")

    return FileResponse(gpkg_path, filename=gpkg_path.name, media_type="application/geopackage+sqlite3")


@router.get("/convert/{job_id}/original-preview/status")
async def get_original_preview_status(job_id: str):
    return _get_preview_status(job_id)


@router.post("/convert/{job_id}/original-preview")
async def start_original_preview(job_id: str):
    job_dir = _job_dir(job_id)
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    current_status = _get_preview_status(job_id)
    if current_status["status"] in {"ready", "running"}:
        return current_status

    source_file = _job_source_file(job_dir)
    if not source_file:
        raise HTTPException(404, "Source file not found")
    gpkg_file = _job_gpkg_file(job_id, job_dir)

    _preview_tasks.add(job_id)
    running_status = _save_preview_status(
        job_id,
        job_dir,
        {
            "status": "running",
            "url": None,
            "message": "正在生成原图预览",
            "updated_at": time.time(),
        },
    )

    async def _run_preview_job() -> None:
        try:
            ok, preview_path, err = await asyncio.to_thread(
                conversion.generate_original_preview,
                source_file,
                job_dir,
                gpkg_file,
            )
            if ok and preview_path:
                _save_preview_status(
                    job_id,
                    job_dir,
                    {
                        "status": "ready",
                        "url": _original_preview_url(job_id),
                        "message": "原图预览已生成",
                        "updated_at": time.time(),
                    },
                )
            else:
                _save_preview_status(
                    job_id,
                    job_dir,
                    {
                        "status": "error",
                        "url": None,
                        "message": err or "原图预览生成失败",
                        "updated_at": time.time(),
                    },
                )
        except Exception as exc:
            _save_preview_status(
                job_id,
                job_dir,
                {
                    "status": "error",
                    "url": None,
                    "message": str(exc),
                    "updated_at": time.time(),
                },
            )
        finally:
            _preview_tasks.discard(job_id)

    asyncio.create_task(_run_preview_job())
    return running_status


@router.get("/convert/{job_id}/original-preview/file")
async def get_original_preview_file(job_id: str):
    job_dir = _job_dir(job_id)
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    preview_path = _original_preview_path(job_dir)
    if not preview_path.exists() or preview_path.stat().st_size == 0:
        raise HTTPException(404, "Original preview is not ready")

    return FileResponse(
        preview_path,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.delete("/jobs/{job_id}", response_model=DeleteJobResponse)
async def delete_job(job_id: str):
    job_dir = _job_dir(job_id)
    runtime_job = _jobs.get(job_id, {})
    meta = _load_job_meta(job_dir) if job_dir.exists() else {}

    if not job_dir.exists() and not runtime_job and not meta:
        raise HTTPException(404, "Job not found")

    layer_name, store_name = _job_names_from_meta(job_id, meta, runtime_job)

    geo_errors: list[str] = []
    if layer_name:
        ok_geo, msg_geo = gs.delete_published_layer(layer_name, store_name)
        if not ok_geo and msg_geo:
            geo_errors.append(msg_geo)

    local_errors: list[str] = []
    try:
        if layer_name:
            manifest_path = _metadata_path(layer_name)
            if manifest_path.exists():
                manifest_path.unlink()
        if job_dir.exists():
            shutil.rmtree(job_dir)
        _jobs.pop(job_id, None)
    except Exception as e:
        local_errors.append(str(e))

    ok = not local_errors
    parts = []
    if geo_errors:
        parts.append(f"GeoServer cleanup failed: {'; '.join(geo_errors)}")
    if local_errors:
        parts.append(f"Local cleanup failed: {'; '.join(local_errors)}")
    if not parts:
        parts.append("Deleted")

    return DeleteJobResponse(
        ok=ok,
        job_id=job_id,
        layer_name=layer_name,
        store_name=store_name,
        message="; ".join(parts),
    )

