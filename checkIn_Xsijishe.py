"""Xsijishe daily sign-in script.

Supports single and multi-account check-in via COOKIE_XSIJISHE environment variable.
Accounts may be separated by a newline or '&&'.
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import Callable
from urllib.parse import unquote

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_URL = "https://xsijishe.com"
SIGN_PAGE_URL = f"{BASE_URL}/k_misign-sign.html"
SIGN_API_URL = f"{BASE_URL}/plugin.php?id=k_misign:sign&operation=qiandao"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": SIGN_PAGE_URL,
}


class ConfigError(ValueError):
    """Raised when COOKIE_XSIJISHE is missing or malformed."""


class XsijisheAPIError(RuntimeError):
    """Raised when the Xsijishe API returns an error or fails."""


def send(title: str, message: str) -> None:
    """Print a notification-compatible summary."""
    print(f"{title}:\n{message}")


def split_account_entries(raw_value: str | None) -> list[str]:
    """Split COOKIE_XSIJISHE into non-empty account entries."""
    if not raw_value or not raw_value.strip():
        raise ConfigError("未配置 COOKIE_XSIJISHE，或变量内容为空")

    entries = [entry.strip() for entry in re.split(r"\r?\n|&&", raw_value)]
    entries = [entry for entry in entries if entry]
    if not entries:
        raise ConfigError("COOKIE_XSIJISHE 中没有可用的账号配置")
    return entries


def parse_account(entry: str, index: int) -> dict[str, str]:
    """Parse and validate one account entry.

    Supported formats:
    1. Key-value format: user=张三; cookie=SgL6_2132_saltkey=...; SgL6_2132_auth=...;
    2. Direct cookie format: SgL6_2132_saltkey=...; SgL6_2132_auth=...;
    """
    account: dict[str, str] = {}
    entry = entry.strip()
    if not entry:
        raise ConfigError(f"第 {index} 个账号配置为空")

    # Extract user if specified
    user_match = re.search(r'(?:^|;)\s*user\s*=\s*([^;]+)', entry, flags=re.IGNORECASE)
    if user_match:
        account["user"] = user_match.group(1).strip()
        # Remove user=... part
        cookie_part = re.sub(r'(?:^|;)\s*user\s*=[^;]+', '', entry, flags=re.IGNORECASE).strip(" ;")
    else:
        cookie_part = entry

    # If cookie_part starts with cookie=, strip it
    cookie_part = re.sub(r'^\s*cookie\s*=\s*', '', cookie_part, flags=re.IGNORECASE).strip(" ;")

    if not cookie_part:
        raise ConfigError(f"第 {index} 个账号缺少有效的 Cookie 配置")

    account["cookie"] = cookie_part
    account.setdefault("user", f"账号{index}")
    return account


class Xsijishe:
    """Client for Xsijishe (Discuz! k_misign plugin)."""

    def __init__(
        self,
        account: dict[str, str],
        session: requests.Session | None = None,
        timeout: int = 20,
    ) -> None:
        self.account = account
        self.session = session or requests.Session()
        self.timeout = timeout
        self.user = account.get("user", "未知用户")
        self.cookie = account.get("cookie", "")

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        headers["Cookie"] = self.cookie
        if extra:
            headers.update(extra)
        return headers

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        try:
            kwargs.setdefault("timeout", self.timeout)
            kwargs.setdefault("headers", self._headers(kwargs.pop("headers", None)))
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.Timeout as exc:
            raise XsijisheAPIError("请求司机社接口超时") from exc
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status else type(exc).__name__
            raise XsijisheAPIError(f"请求司机社接口失败（{detail}）") from exc

    @staticmethod
    def _parse_stats(html: str) -> dict[str, str]:
        """Extract check-in statistics from page HTML.

        Target attributes:
        - 连续签到 (id="lxdays")
        - 签到等级 (id="lxlevel")
        - 积分奖励 (id="lxreward")
        - 总天数 (id="lxtdays")
        """
        stats: dict[str, str] = {
            "lxdays": "",
            "lxlevel": "",
            "lxreward": "",
            "lxtdays": "",
        }
        for key in ("lxdays", "lxlevel", "lxreward", "lxtdays"):
            m = re.search(rf'id=["\']{key}["\'][^>]*value=["\']([^"\']*)["\']', html)
            if not m:
                m = re.search(rf'value=["\']([^"\']*)["\'][^>]*id=["\']{key}["\']', html)
            if m and m.group(1).strip():
                stats[key] = m.group(1).strip()

        # Fallback to <h4> headings if input values were not matched
        heading_map = [
            ("lxdays", "连续签到"),
            ("lxlevel", "签到等级"),
            ("lxreward", "积分奖励"),
            ("lxtdays", "总天数"),
        ]
        for key, heading in heading_map:
            if not stats[key]:
                m = re.search(
                    rf'<li[^>]*>[\s\S]*?<h4>\s*{heading}\s*</h4>([\s\S]*?)</li>',
                    html,
                )
                if m:
                    li_content = m.group(1)
                    val_m = re.search(r'value=["\']([^"\']+)["\']', li_content) or re.search(r'>(\d+)<', li_content)
                    if val_m:
                        stats[key] = val_m.group(1).strip()

        return stats

    def get_sign_page(self) -> dict:
        """Fetch the sign-in page and parse user status and formhash."""
        resp = self._request("GET", SIGN_PAGE_URL)
        html = resp.text

        # 1. Check if user is logged in
        is_guest = False
        if "discuz_uid = '0'" in html or 'discuz_uid = "0"' in html:
            is_guest = True
        elif 'member.php?mod=logging&amp;action=login' in html and 'JD_sign' in html:
            jd_sign_match = re.search(r'id=["\']JD_sign["\'][^>]*href=["\']([^"\']+)["\']', html)
            if jd_sign_match and "login" in jd_sign_match.group(1):
                is_guest = True

        if is_guest:
            raise XsijisheAPIError("账号 Cookie 已失效或未登录，请重新获取")

        # 2. Extract formhash
        formhash_match = (
            re.search(r'name=["\']formhash["\']\s+value=["\']([a-zA-Z0-9]+)["\']', html)
            or re.search(r'var\s+FORMHASH\s*=\s*[\'"]([a-zA-Z0-9]+)[\'"]', html)
            or re.search(r'formhash=([a-zA-Z0-9]{8})', html)
        )
        if not formhash_match:
            raise XsijisheAPIError("无法从签到页面解析到 formhash 安全凭证")
        formhash = formhash_match.group(1)

        # 3. Extract user nickname if available in page
        username = self.user
        name_match = (
            re.search(r'<strong class="vwmy"><a[^>]*>([^<]+)</a>', html)
            or re.search(r'<a[^>]*class="author"[^>]*>([^<]+)</a>', html)
        )
        if name_match and name_match.group(1).strip():
            username = f"{self.user} ({name_match.group(1).strip()})"

        # 4. Extract check-in statistics
        stats = self._parse_stats(html)
        consecutive_days = int(stats["lxdays"]) if stats["lxdays"].isdigit() else 0

        # Check if already signed in today
        already_signed = False
        if "今日已签" in html or "今日已签到" in html:
            already_signed = True
        elif re.search(r'id=["\']JD_sign["\'][^>]*class=["\'][^"\']*(?:haveread|signed)[^"\']*["\']', html):
            already_signed = True

        return {
            "formhash": formhash,
            "username": username,
            "consecutive_days": consecutive_days,
            "already_signed": already_signed,
            "stats": stats,
            "html": html,
        }

    def sign_in(self, formhash: str) -> str:
        """Perform sign-in request using formhash."""
        # Discuz! k_misign plugin AJAX sign-in endpoint
        ajax_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": SIGN_PAGE_URL,
        }

        # Try GET request first (the standard k_misign trigger)
        sign_url = f"{SIGN_API_URL}&format=button&formhash={formhash}"
        resp = self._request("GET", sign_url, headers=ajax_headers)
        content = resp.text

        # Extract message from XML/CDAT or HTML response
        cdata_match = re.search(r'<!\[CDATA\[([\s\S]*?)\]\]>', content)
        msg = cdata_match.group(1) if cdata_match else content

        # Clean tags
        clean_msg = re.sub(r'<[^>]+>', ' ', msg).strip()
        clean_msg = ' '.join(clean_msg.split())

        if "今日已签" in clean_msg or "已经签到" in clean_msg:
            return "今日已完成签到"
        if "签到成功" in clean_msg or "恭喜" in clean_msg:
            return clean_msg or "签到成功"

        # If Discuz! returned a general message
        if clean_msg:
            return clean_msg

        return "签到请求已提交"

    def do_sign(self, wait_after_sign: float | None = None) -> str:
        """Orchestrate the sign-in workflow for this account."""
        if wait_after_sign is None:
            wait_env = os.getenv("SIGN_WAIT_SECONDS")
            wait_after_sign = float(wait_env) if wait_env else 3.0

        info = self.get_sign_page()
        username = info["username"]

        if info["already_signed"]:
            status_line = "✅ 今日已签到，无需重复打卡"
            stats = info["stats"]
        else:
            reward_msg = self.sign_in(info["formhash"])
            status_line = f"🎉 签到结果：{reward_msg}"
            # 签到完成后等待片刻，重新获取网页最新统计属性
            if wait_after_sign > 0:
                time.sleep(wait_after_sign)
            try:
                updated_info = self.get_sign_page()
                stats = updated_info["stats"]
            except Exception:
                stats = info["stats"]

        lxdays = stats.get("lxdays") or str(info.get("consecutive_days") or 0)
        lxlevel = stats.get("lxlevel") or "1"
        lxreward = stats.get("lxreward") or "0"
        lxtdays = stats.get("lxtdays") or lxdays

        level_str = f"Lv.{lxlevel}" if lxlevel.isdigit() else lxlevel
        reward_str = f"+{lxreward}" if lxreward.isdigit() and not lxreward.startswith("+") else lxreward

        lines = [
            f"👤 用户：{username}",
            f"📊 连续签到：{lxdays} 天",
            f"🎖️ 签到等级：{level_str}",
            f"🎁 积分奖励：{reward_str}",
            f"📅 总天数：{lxtdays} 天",
            status_line,
        ]

        return "\n".join(lines)


def main(
    cookie_value: str | None = None,
    client_factory: Callable[[dict[str, str]], Xsijishe] | None = None,
) -> int:
    """Run every configured account and return a process-compatible exit code."""
    print("----------司机社每日签到开始----------")
    if cookie_value is None:
        cookie_value = os.getenv("COOKIE_XSIJISHE")
    client_factory = client_factory or Xsijishe

    try:
        entries = split_account_entries(cookie_value)
    except ConfigError as exc:
        print(f"❌ {exc}")
        return 2

    print(f"✅ 检测到共 {len(entries)} 个司机社账号\n")
    results: list[str] = []
    failures = 0

    for index, entry in enumerate(entries, start=1):
        heading = f"🙍🏻‍♂️ 第 {index} 个账号"
        try:
            account = parse_account(entry, index)
            result = client_factory(account).do_sign()
            results.append(f"{heading}\n{result}")
        except (ConfigError, XsijisheAPIError, KeyError, TypeError, ValueError) as exc:
            failures += 1
            results.append(f"{heading}\n❌ {exc}")
        except Exception as exc:  # Keep later accounts running on unexpected errors.
            failures += 1
            results.append(f"{heading}\n❌ 未知错误：{type(exc).__name__} - {exc}")

    summary = "\n\n".join(results)
    send("司机社自动签到", summary)
    print(
        f"\n----------执行完毕：成功 {len(entries) - failures}，失败 {failures}----------"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
