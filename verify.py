"""MailVerify 核心 4 步验证算法"""
import asyncio
import re
import time
from dataclasses import dataclass, asdict
from typing import Optional

import dns.resolver
import dns.exception

# ── 一次性邮箱域名黑名单（top 50） ──
DISPOSABLE_DOMAINS = {
    "10minutemail.com", "temp-mail.org", "guerrillamail.com", "tempmail.com",
    "throwaway.email", "mailinator.com", "trashmail.com", "yopmail.com",
    "tempinbox.com", "temp-mail.io", "emailondeck.com", "discard.email",
    "tempemail.co", "tempemail.com", "emailtemp.org", "tempmail.org",
    "temp-mail.net", "temporaryemail.net", "tempmailaddress.com",
    "temp.email", "tempmail.de", "mail.tm", "inbox.lv", "sharklasers.com",
    "guerrillamailblock.com", "grr.la", "pokemail.net", "s0ny.net",
    "mail.eintrittskarten.tk", "speed.1s.fr", "trashmail.fr", "trashmail.me",
    "dispostable.com", "maildrop.cc", "mintemail.com", "jetable.org",
    "nada.ltdkhan.xyz", "yopmail.fr", "yopmail.net", "cool.fr.nf",
    "jetable.fr.nf", "grr.la", "courriel.fr.nf", "courriels.com",
    "gettempmail.com", "tempmail.net", "temp-mail.fr", "tempemail.net",
}

# ── 角色邮箱关键词 ──
ROLE_BASED_KEYWORDS = {
    "admin", "administrator", "info", "support", "sales", "contact",
    "help", "helpdesk", "postmaster", "hostmaster", "webmaster", "abuse",
    "noc", "security", "operations", "ops", "dev", "developer", "team",
    "hello", "hi", "office", "billing", "accounts", "payments", "hr",
    "recruit", "employment", "feedback", "newsletter", "subscribe",
}

# ── SMTP 发件地址（HELO + MAIL FROM） ──
HELO_HOST = "mailverify.app"
MAIL_FROM = "verify@mailverify.app"

# ── 默认超时 ──
DEFAULT_TIMEOUT = 30
SMTP_CONNECT_TIMEOUT = 20
SMTP_COMMAND_TIMEOUT = 15
CATCHALL_SMTP_TIMEOUT = 10


@dataclass
class VerifyResult:
    email: str
    status: str  # valid | invalid | risky | unknown | catchall_risk | disposable
    reason: Optional[str] = None
    score: int = 0
    checks: dict = None
    mx_records: list = None
    smtp_response: Optional[str] = None
    latency_ms: int = 0

    def to_dict(self):
        return asdict(self)


# ── Step 1: 格式检查 ──
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def check_format(email: str) -> bool:
    return bool(EMAIL_RE.match(email))


# ── Step 2: MX 检查 ──
def check_mx(domain: str) -> tuple[bool, list]:
    """返回 (has_mx, mx_records)"""
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=10)
        records = []
        for r in answers:
            records.append({
                "priority": r.preference,
                "exchange": str(r.exchange).rstrip("."),
            })
        records.sort(key=lambda x: x["priority"])
        return len(records) > 0, records
    except dns.exception.Timeout:
        return False, []
    except dns.resolver.NXDOMAIN:
        return False, []
    except dns.resolver.NoAnswer:
        return False, []
    except Exception:
        return False, []


def is_disposable(domain: str) -> bool:
    domain_lower = domain.lower()
    if domain_lower in DISPOSABLE_DOMAINS:
        return True
    # 子域名也检查：xxx.temp-mail.org
    for d in DISPOSABLE_DOMAINS:
        if domain_lower.endswith("." + d):
            return True
    return False


def is_role_based(local_part: str) -> bool:
    lp = local_part.lower().split(".")[0]  # 取第一段
    return lp in ROLE_BASED_KEYWORDS


# ── Step 3: SMTP 握手 ──
async def smtp_handshake(host: str, port: int = 25) -> tuple[int, str]:
    """
    做 HELO → MAIL FROM → RCPT TO，返回 (code, message)
    注意：MAIL FROM 设为 DSN 地址（不带真实邮箱前缀）避免被当作垃圾
    """
    reader, writer = None, None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=SMTP_CONNECT_TIMEOUT,
        )

        # 读欢迎语
        greeting = await asyncio.wait_for(reader.readline(), timeout=SMTP_COMMAND_TIMEOUT)
        # 不用检查码，很多服务器欢迎语就是 220

        # HELO
        writer.write(f"HELO {HELO_HOST}\r\n".encode())
        await writer.drain()
        helo_resp = await asyncio.wait_for(reader.readline(), timeout=SMTP_COMMAND_TIMEOUT)

        # MAIL FROM
        writer.write(f"MAIL FROM:<{MAIL_FROM}>\r\n".encode())
        await writer.drain()
        mail_resp = await asyncio.wait_for(reader.readline(), timeout=SMTP_COMMAND_TIMEOUT)

        # RCPT TO — 这里只返回通道，让调用方指定收件人
        # 我们先返回通道让外层继续发
        return 0, "channel_ready", reader, writer

    except asyncio.TimeoutError:
        return -1, "timeout", None, None
    except ConnectionRefusedError:
        return -2, "connection_refused", None, None
    except OSError as e:
        return -3, f"os_error:{e}", None, None
    except Exception as e:
        return -9, f"unknown:{e}", None, None


async def smtp_rcpt(reader, writer, rcpt_to: str) -> tuple[int, str]:
    """在已建立的 SMTP 通道上发 RCPT TO"""
    try:
        writer.write(f"RCPT TO:<{rcpt_to}>\r\n".encode())
        await writer.drain()
        resp = await asyncio.wait_for(reader.readline(), timeout=SMTP_COMMAND_TIMEOUT)
        text = resp.decode(errors="replace").strip()
        # 可能多行响应：250-mail.example.com\n250 OK
        # 继续读直到没有 - 前缀
        while text.startswith(("250-", "450-", "451-", "452-", "550-", "551-", "552-", "553-", "554-", "421-")):
            try:
                next_line = await asyncio.wait_for(reader.readline(), timeout=2)
                if not next_line:
                    break
                ntext = next_line.decode(errors="replace").strip()
                if ntext.startswith(tuple(text[:3] + "-" for text in text.split())):
                    text += " " + ntext
                else:
                    break
            except Exception:
                break

        code_match = re.match(r"^(\d{3})", text)
        code = int(code_match.group(1)) if code_match else 0
        return code, text
    except asyncio.TimeoutError:
        return -1, "timeout"
    except Exception as e:
        return -9, f"error:{e}"


async def smtp_quit(reader, writer):
    try:
        writer.write(b"QUIT\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass


async def do_smtp_check(mx_hosts: list, target_email: str,
                        do_catchall: bool = True) -> tuple[str, Optional[str], str, Optional[bool]]:
    """
    在 MX 服务器上做 SMTP 握手 + RCPT TO + 可选 catch-all 检测
    返回 (status, reason, smtp_response, is_catchall)
    """
    # 尝试每个 MX 服务器，直到有一个响应
    last_smtp_response = None
    smtp_status = None

    for mx in mx_hosts[:3]:  # 最多试前 3 个 MX
        host = mx["exchange"]
        code, msg, reader, writer = await smtp_handshake(host)
        if reader is None:
            last_smtp_response = f"{code} {msg} ({host})"
            continue

        # 对真实邮箱发 RCPT TO
        rcpt_code, rcpt_msg = await smtp_rcpt(reader, writer, target_email)
        last_smtp_response = rcpt_msg

        if rcpt_code == 250:
            # ✅ 有效！
            smtp_status = "valid"
            reason = None
            is_catchall = False

            # ── Step 4: Catch-all 检测 ──
            if do_catchall:
                # 发一个明显不存在的随机地址
                fake_local = "zzzzz_random_nonexistent_abc123_xyz789"
                at_idx = target_email.index("@")
                fake_email = fake_local + target_email[at_idx:]
                fake_code, fake_msg = await smtp_rcpt(reader, writer, fake_email)

                if fake_code == 250:
                    # catch-all！域名任何地址都收
                    is_catchall = True
                    smtp_status = "catchall_risk"
                    reason = None
                elif fake_code in (550, 551, 553):
                    # 正常拒绝 → 不是 catch-all
                    is_catchall = False
                else:
                    # 不确定，保守标记
                    is_catchall = None

            await smtp_quit(reader, writer)
            return smtp_status, reason, last_smtp_response, is_catchall

        elif rcpt_code in (550, 551, 553):
            # ❌ 用户不存在 / 域名无效
            smtp_status = "invalid"
            reason = "not_found"
            await smtp_quit(reader, writer)
            return smtp_status, reason, last_smtp_response, False

        elif rcpt_code == 554:
            smtp_status = "invalid"
            reason = "transaction_failed"
            await smtp_quit(reader, writer)
            return smtp_status, reason, last_smtp_response, False

        elif rcpt_code in (450, 451, 452):
            # ⏳ Greylisting / 临时拒绝
            smtp_status = "risky"
            reason = "greylisted"
            await smtp_quit(reader, writer)
            return smtp_status, reason, last_smtp_response, None

        elif rcpt_code == 421:
            smtp_status = "risky"
            reason = "deferred"
            await smtp_quit(reader, writer)
            return smtp_status, reason, last_smtp_response, None

        elif rcpt_code == -1:
            # 超时，换下一个 MX
            await smtp_quit(reader, writer)
            continue

        else:
            # 未知响应
            await smtp_quit(reader, writer)
            smtp_status = "unknown"
            reason = "unknown_response"
            return smtp_status, reason, last_smtp_response, None

    # 所有 MX 都试完了，没有拿到 250/550 的明确响应
    if smtp_status is None:
        smtp_status = "unknown"
        reason = "all_mx_unreachable"
    return smtp_status, reason, last_smtp_response, None


# ── 主验证函数 ──
async def verify_email(email: str, timeout: int = DEFAULT_TIMEOUT) -> VerifyResult:
    start = time.time()
    checks = {"format": False, "mx": False, "smtp": False,
              "catchall": False, "disposable": False, "role_based": False}
    mx_records = None

    # Step 1: 格式
    if not check_format(email):
        latency = int((time.time() - start) * 1000)
        return VerifyResult(
            email=email, status="invalid", reason="format",
            score=0, checks=checks, latency_ms=latency,
        )
    checks["format"] = True

    # 拆 local@domain
    at_idx = email.rfind("@")
    local_part = email[:at_idx]
    domain = email[at_idx + 1:]

    # Step 1.5: Role-based
    if is_role_based(local_part):
        checks["role_based"] = True

    # Step 1.6: Disposable
    if is_disposable(domain):
        checks["disposable"] = True
        latency = int((time.time() - start) * 1000)
        return VerifyResult(
            email=email, status="disposable", reason="disposable",
            score=5, checks=checks, latency_ms=latency,
        )

    # Step 2: MX
    has_mx, mx_records = check_mx(domain)
    if not has_mx:
        latency = int((time.time() - start) * 1000)
        return VerifyResult(
            email=email, status="invalid", reason="no_mx",
            score=10, checks=checks, mx_records=mx_records, latency_ms=latency,
        )
    checks["mx"] = True

    # Step 3+4: SMTP + Catch-all
    smtp_status, reason, smtp_resp, is_catchall = await do_smtp_check(
        mx_records, email, do_catchall=True,
    )
    checks["smtp"] = smtp_status in ("valid", "catchall_risk", "invalid")

    if is_catchall is True:
        checks["catchall"] = True

    # 计算分数
    score = _compute_score(smtp_status, checks, is_catchall)

    latency = int((time.time() - start) * 1000)
    return VerifyResult(
        email=email,
        status=smtp_status,
        reason=reason,
        score=score,
        checks=checks,
        mx_records=mx_records,
        smtp_response=smtp_resp,
        latency_ms=latency,
    )


def _compute_score(status: str, checks: dict, is_catchall: Optional[bool]) -> int:
    if status == "valid":
        score = 95
        if checks.get("role_based"):
            score -= 5
        return score
    elif status == "catchall_risk":
        return 55
    elif status == "risky":
        return 65
    elif status == "disposable":
        return 5
    elif status == "invalid":
        if checks.get("mx"):
            return 15  # 有 MX 但 SMTP 拒绝 = 真无效
        return 25  # 无 MX
    elif status == "unknown":
        return 40
    return 30
