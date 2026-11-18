"""MailVerify FastAPI 入口"""
import io
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from verify import verify_email
from batch import (
    create_job, get_job, get_job_results, generate_csv,
    parse_csv, parse_json_list, JOBS,
)

app = FastAPI(
    title="MailVerify API",
    description="Email verification with SMTP handshake + catch-all + greylisting",
    version="1.0.0",
)

# CORS — 允许 Cloudflare Pages 前端 + localhost 开发
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:8765",
        "http://localhost:8766",
        "http://localhost:5173",
        "http://localhost:4173",
        "https://mailverify.app",
        "https://*.pages.dev",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求模型 ──
class VerifyRequest(BaseModel):
    email: str
    timeout: int = 10


class BatchJsonRequest(BaseModel):
    emails: list[str]


# ── 路由 ──
@app.get("/health")
async def health():
    return {"status": "ok", "jobs_in_memory": len(JOBS)}


@app.post("/verify")
async def api_verify(req: VerifyRequest):
    """单邮箱验证"""
    if not req.email:
        raise HTTPException(status_code=400, detail="email required")
    result = await verify_email(req.email, timeout=req.timeout)
    return result.to_dict()


@app.post("/batch")
async def api_batch(
    file: Optional[UploadFile] = File(None),
    body: Optional[BatchJsonRequest] = None,
):
    """
    批量验证 — 支持两种方式:
    1. multipart/form-data 上传 CSV 文件
    2. JSON body {"emails": ["a@b.com", ...]}
    """
    email_list = []

    if file is not None:
        # CSV 上传
        content = await file.read()
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        email_list = parse_csv(text)
    elif body is not None:
        # JSON 数组
        email_list = parse_json_list(body.model_dump())

    if not email_list:
        raise HTTPException(status_code=400, detail="no emails found in input")

    if len(email_list) > 100_000:
        raise HTTPException(status_code=400, detail="max 100,000 emails per batch")

    job_id = create_job(email_list)
    job = JOBS[job_id]
    return {
        "job_id": job_id,
        "total": job["total"],
        "processed": 0,
        "status": job["status"],
    }


@app.get("/result/{job_id}")
async def api_result(job_id: str):
    """查批量任务状态 + 统计"""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/result/{job_id}/download")
async def api_download(job_id: str, type: str = Query("all", pattern="^(all|valid|invalid|risky|disposable|catchall_risk|unknown)$")):
    """
    下载 CSV 结果
    type: all | valid | invalid | risky | disposable | catchall_risk | unknown
    """
    csv_text = generate_csv(job_id, type)
    if csv_text is None:
        raise HTTPException(status_code=404, detail="job not found")

    filename = f"mailverify_{job_id}_{type}.csv"
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/result/{job_id}/results")
async def api_results_list(job_id: str, type: str = Query("all")):
    """拿结果 JSON 列表（给前端 dashboard 展示）"""
    results = get_job_results(job_id, type)
    if results is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job_id": job_id, "type": type, "count": len(results), "results": results}
