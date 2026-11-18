"""MailVerify 批量验证 — asyncio.Semaphore 并发控制 + CSV 处理"""
import asyncio
import csv
import io
import uuid
import time
from collections import Counter
from typing import Optional

from verify import verify_email, VerifyResult

# 内存存储批量任务（简单起步，之后换 Render PostgreSQL）
JOBS: dict[str, dict] = {}

# 并发控制 — 同时最多 50 路 SMTP
SEMAPHORE = asyncio.Semaphore(50)


async def _verify_one(email: str) -> VerifyResult:
    async with SEMAPHORE:
        return await verify_email(email)


async def batch_verify(email_list: list[str], job_id: str):
    """后台任务 — 批量验证，更新 JOBS 字典里的进度"""
    job = JOBS[job_id]
    job["total"] = len(email_list)
    job["processed"] = 0
    job["results"] = []
    job["status"] = "processing"
    job["started_at"] = time.time()

    # 并发跑 — as_completed 逐个收，实时更新进度
    tasks = {asyncio.create_task(_verify_one(e)): i
             for i, e in enumerate(email_list)}

    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
            job["results"].append(result)
        except Exception as exc:
            idx = tasks[coro]
            job["results"].append(VerifyResult(
                email=email_list[idx],
                status="unknown",
                reason=f"exception:{exc}",
                score=30,
            ))
        job["processed"] += 1

    # 按原始顺序排序
    index_map = {e: i for i, e in enumerate(email_list)}
    job["results"].sort(key=lambda r: index_map.get(r.email, 9999))

    job["status"] = "done"
    job["finished_at"] = time.time()


def create_job(email_list: list[str]) -> str:
    """创建批量任务，返回 job_id（后台异步跑）"""
    job_id = "batch_" + uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "total": len(email_list),
        "processed": 0,
        "results": [],
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
    }
    asyncio.create_task(batch_verify(email_list, job_id))
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    job = JOBS.get(job_id)
    if job is None:
        return None
    return _job_to_api(job)


def _job_to_api(job: dict) -> dict:
    results = job.get("results", [])
    stats = {}
    if results:
        status_counts = Counter(r.status for r in results)
        reason_counts = Counter(r.reason for r in results if r.reason)
        valid_count = status_counts.get("valid", 0)
        total = len(results)
        stats = {
            "valid_count": status_counts.get("valid", 0),
            "invalid_count": status_counts.get("invalid", 0),
            "risky_count": status_counts.get("risky", 0),
            "disposable_count": status_counts.get("disposable", 0),
            "catchall_count": status_counts.get("catchall_risk", 0),
            "unknown_count": status_counts.get("unknown", 0),
            "valid_rate": round(valid_count / total * 100, 1) if total else 0,
            "top_invalid_reasons": reason_counts.most_common(5),
        }

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "total": job["total"],
        "processed": job["processed"],
        "progress_pct": round(job["processed"] / max(job["total"], 1) * 100, 1),
        "created_at": job["created_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "stats": stats,
    }


def get_job_results(job_id: str, result_type: str = "all") -> Optional[list[dict]]:
    job = JOBS.get(job_id)
    if job is None:
        return None
    results = job.get("results", [])
    if result_type != "all":
        results = [r for r in results if r.status == result_type]
    return [r.to_dict() for r in results]


def generate_csv(job_id: str, result_type: str = "all") -> Optional[str]:
    job = JOBS.get(job_id)
    if job is None:
        return None
    results = job.get("results", [])
    if result_type != "all":
        results = [r for r in results if r.status == result_type]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "status", "reason", "score", "smtp_response", "latency_ms"])
    for r in results:
        writer.writerow([
            r.email, r.status, r.reason or "", r.score,
            r.smtp_response or "", r.latency_ms,
        ])
    return output.getvalue()


def parse_csv(content: str) -> list[str]:
    """从 CSV 内容里提取 email 列"""
    emails = []
    reader = csv.reader(io.StringIO(content))
    try:
        header = next(reader)
        email_col_idx = None
        email_col_names = {"email", "email_address", "emailaddress",
                           "mail", "address", "contact_email"}
        for i, h in enumerate(header):
            if h.strip().lower() in email_col_names:
                email_col_idx = i
                break

        if email_col_idx is None:
            email_col_idx = 0
            # 如果 header 第一行本身像邮箱
            if "@" in header[0]:
                emails.append(header[0].strip())

        for row in reader:
            if len(row) > email_col_idx:
                val = row[email_col_idx].strip()
                if val and "@" in val:
                    emails.append(val)
    except StopIteration:
        pass

    return list(dict.fromkeys(emails))


def parse_json_list(data: dict) -> list[str]:
    emails = data.get("emails", [])
    if isinstance(emails, list):
        return [e.strip() for e in emails if isinstance(e, str) and "@" in e]
    return []
