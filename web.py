from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

ASSETS = Path(__file__).parent / "assets"


async def admin(request: Request, response: Response):
    # Never pass credentials in URLs. The core dependency also accepts query tokens;
    # this plugin requires the Authorization header before invoking that dependency.
    if request.query_params.get("token") or not request.headers.get("Authorization", "").startswith("Bearer "):
        raise HTTPException(401, "请登录 Nekro Agent 后台")
    from nekro_agent.services.user.deps import get_current_user
    from nekro_agent.services.user.role import Role
    user = await get_current_user(request)
    if not user.is_active or user.perm_level < Role.Admin:
        raise HTTPException(403, "仅后台管理员可查看群关系数据")
    response.headers["Cache-Control"] = "no-store"
    return user


class ReportRequest(BaseModel):
    chat_key: str = Field(min_length=1, max_length=128)
    days: int = Field(default=7, ge=1, le=30)
    limit: int = Field(default=20, ge=2, le=40)
    refresh: bool = False
    ai: bool = False


class ToggleRequest(BaseModel):
    chat_key: str = Field(min_length=1, max_length=128)
    enabled: bool


class ClearRequest(BaseModel):
    chat_key: str = Field(min_length=1, max_length=128)
    confirmation: str


def create_router(get_service):
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard():
        return HTMLResponse((ASSETS / "index.html").read_text(encoding="utf-8"), headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"})

    @router.get("/assets/{name}", include_in_schema=False)
    async def asset(name: str):
        if name not in {"app.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(ASSETS / name, media_type="text/javascript" if name.endswith(".js") else "text/css")

    @router.get("/api/channels", dependencies=[Depends(admin)])
    async def channels():
        return {"channels": await get_service().channels()}

    @router.post("/api/report", dependencies=[Depends(admin)])
    async def report(body: ReportRequest):
        try:
            data = await get_service().report(body.chat_key, body.days, body.limit, refresh=body.refresh, ai=body.ai)
            return data
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @router.get("/api/image", dependencies=[Depends(admin)])
    async def image(chat_key: str = Query(max_length=128), days: int = Query(default=7, ge=1, le=30), limit: int = Query(default=20, ge=2, le=40)):
        try:
            result = await get_service().report(chat_key, days, limit)
            path = await get_service().image(result)
            return FileResponse(path, media_type="image/png", filename="group-relations.png", headers={"Cache-Control": "no-store"})
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(503, "图片渲染失败，仍可查看看板或下载 SVG。请检查渲染服务。") from e

    @router.get("/api/svg", dependencies=[Depends(admin)])
    async def svg(chat_key: str = Query(max_length=128), days: int = Query(default=7, ge=1, le=30), limit: int = Query(default=20, ge=2, le=40)):
        try:
            result = await get_service().report(chat_key, days, limit)
            return Response(result["svg"], media_type="image/svg+xml", headers={"Content-Disposition": 'attachment; filename="group-relations.svg"', "Cache-Control": "no-store"})
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @router.post("/api/toggle", dependencies=[Depends(admin)])
    async def toggle(body: ToggleRequest):
        svc = get_service()
        try:
            await svc.channel(body.chat_key)
            await asyncio.to_thread(svc.repo.set_enabled, body.chat_key, body.enabled)
            svc.invalidate(body.chat_key)
            return {"ok": True}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @router.post("/api/clear", dependencies=[Depends(admin)])
    async def clear(body: ClearRequest):
        svc = get_service()
        if body.confirmation != "清空本群":
            raise HTTPException(400, "请填写确认文字：清空本群")
        try:
            await svc.channel(body.chat_key)
            await asyncio.to_thread(svc.repo.clear, body.chat_key)
            await asyncio.to_thread(svc.purge_exports)
            svc.invalidate(body.chat_key)
            return {"ok": True}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    return router
