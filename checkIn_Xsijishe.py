"""Xsijishe daily sign-in script.

Supports single and multi-account check-in via COOKIE_XSIJISHE environment variable.
Accounts may be separated by a newline or '&&'.
"""

from __future__ import annotations

import os
import re
import socket
import sys
import time
from typing import Callable
from urllib.parse import unquote, urlparse

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_URL = "https://xsijishe.com"
DEFAULT_BASE_URL = "https://xsijishe.com"
SIGN_PAGE_URL = f"{BASE_URL}/k_misign-sign.html"
SIGN_API_URL = f"{BASE_URL}/plugin.php?id=k_misign:sign&operation=qiandao"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/155.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": os.getenv("USER_AGENT") or DEFAULT_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Chromium";v="155", "Google Chrome";v="155", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "Referer": SIGN_PAGE_URL,
}


def normalize_base_url(url: str | None) -> str:
    """Normalize base URL to scheme://netloc without trailing slash or path."""
    if not url or not url.strip():
        return DEFAULT_BASE_URL
    clean = url.strip()
    if not (clean.startswith("http://") or clean.startswith("https://")):
        clean = f"https://{clean}"
    parsed = urlparse(clean)
    if not parsed.netloc:
        return DEFAULT_BASE_URL
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def get_configured_proxy_url() -> str | None:
    """Retrieve configured reverse proxy URL from environment variables."""
    raw = (
        os.getenv("VERCEL_PROXY_URL")
        or os.getenv("PROXY_URL")
        or os.getenv("CF_WORKER_URL")
        or os.getenv("BASE_URL")
    )
    if raw and raw.strip():
        base = normalize_base_url(raw)
        if base != DEFAULT_BASE_URL:
            return base
    return None


def get_access_mode_desc(base_url: str) -> str:
    """Return a descriptive label for the current access mode."""
    if not base_url or base_url == DEFAULT_BASE_URL:
        return f"直连目标站点 ({DEFAULT_BASE_URL})"
    lower = base_url.lower()
    if "vercel.app" in lower:
        return f"Vercel 反向代理 ({base_url})"
    if "workers.dev" in lower:
        return f"Cloudflare Worker 反代 ({base_url})"
    return f"反向代理 ({base_url})"


def check_network_connectivity(timeout: float = 5.0) -> dict[str, str]:
    """Diagnose local egress IP, remote target DNS resolution, and TCP/HTTP reachability."""
    configured_base = get_configured_proxy_url()
    if configured_base:
        access_mode = get_access_mode_desc(configured_base)
        probe_url = f"{configured_base}/k_misign-sign.html"
    else:
        access_mode = f"直连目标站点 ({DEFAULT_BASE_URL})"
        probe_url = f"{DEFAULT_BASE_URL}/k_misign-sign.html"

    report = {
        "access_mode": access_mode,
        "local_ip": "未知",
        "remote_ips": "解析失败",
        "tcp_status": "未知",
        "gateway_status": "未知",
    }

    # 1. Local Egress IP (test against multiple public lookup services)
    ip_services = [
        "https://api.ipify.org?format=json",
        "https://httpbin.org/ip",
        "https://ifconfig.me/all.json",
    ]
    for url in ip_services:
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                ip_val = data.get("ip") or data.get("origin") or data.get("ip_addr")
                if ip_val:
                    report["local_ip"] = str(ip_val).split(",")[0].strip()
                    break
        except Exception:
            continue

    # 2. Remote IP resolution
    host = "xsijishe.com"
    ips: list[str] = []
    try:
        resolved = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        ips = sorted(list(set(item[4][0] for item in resolved)))
        report["remote_ips"] = ", ".join(ips) if ips else "未返回解析地址"
    except Exception as exc:
        report["remote_ips"] = f"解析异常: {exc}"

    # 3. TCP Connect check
    first_ip = ips[0] if ips else host
    t0 = time.time()
    try:
        with socket.create_connection((first_ip, 443), timeout=timeout):
            ms = int((time.time() - t0) * 1000)
            report["tcp_status"] = f"正常 (握手延迟: {ms}ms)"
    except Exception as exc:
        report["tcp_status"] = f"连接失败 ({exc})"

    # 4. Probe HTTP Gateway
    try:
        probe_resp = requests.get(
            probe_url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
        )
        cf_ray = probe_resp.headers.get("cf-ray", "")
        server = probe_resp.headers.get("server", "")
        if probe_resp.status_code == 200:
            report["gateway_status"] = f"HTTP 200 正常 (Server: {server or '未知'})"
        elif probe_resp.status_code == 403:
            text = probe_resp.text or ""
            if (
                "Just a moment" in text
                or "challenges.cloudflare.com" in text
                or "challenge-platform" in text
                or "__CF$cv$params" in text
                or "cf-mitigated" in probe_resp.headers
            ):
                report["gateway_status"] = f"HTTP 403 [Cloudflare 5秒盾拦截] (CF-Ray: {cf_ray or '无'})"
            else:
                report["gateway_status"] = f"HTTP 403 拒绝访问 (CF-Ray: {cf_ray or '无'})"
        else:
            report["gateway_status"] = f"HTTP {probe_resp.status_code} (CF-Ray: {cf_ray or '无'})"
    except Exception as exc:
        report["gateway_status"] = f"请求探测异常: {exc}"

    return report


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
        cookie_part = re.sub(r'(?:^|;)\s*user\s*=[^;]+', '', entry, flags=re.IGNORECASE).strip(" ;")
    else:
        cookie_part = entry

    # Extract proxy if specified
    proxy_match = re.search(r'(?:^|;)\s*proxy\s*=\s*([^;]+)', cookie_part, flags=re.IGNORECASE)
    if proxy_match:
        account["proxy"] = proxy_match.group(1).strip()
        cookie_part = re.sub(r'(?:^|;)\s*proxy\s*=[^;]+', '', cookie_part, flags=re.IGNORECASE).strip(" ;")

    # Extract reverse proxy / base url if specified
    for kw in ("vercel_url", "proxy_url", "worker", "base_url"):
        kw_match = re.search(rf'(?:^|;)\s*{kw}\s*=\s*([^;]+)', cookie_part, flags=re.IGNORECASE)
        if kw_match:
            account[kw] = kw_match.group(1).strip()
            cookie_part = re.sub(rf'(?:^|;)\s*{kw}\s*=[^;]+', '', cookie_part, flags=re.IGNORECASE).strip(" ;")

    # Extract custom user agent if specified
    ua_match = re.search(r'(?:^|;)\s*(?:user_agent|ua)\s*=\s*([^;]+)', cookie_part, flags=re.IGNORECASE)
    if ua_match:
        account["user_agent"] = ua_match.group(1).strip()
        cookie_part = re.sub(r'(?:^|;)\s*(?:user_agent|ua)\s*=[^;]+', '', cookie_part, flags=re.IGNORECASE).strip(" ;")

    # Extract sign mode if specified (e.g. mode=browser or mode=http)
    mode_match = re.search(r'(?:^|;)\s*mode\s*=\s*([^;]+)', cookie_part, flags=re.IGNORECASE)
    if mode_match:
        account["mode"] = mode_match.group(1).strip()
        cookie_part = re.sub(r'(?:^|;)\s*mode\s*=[^;]+', '', cookie_part, flags=re.IGNORECASE).strip(" ;")

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

        # Check whether browser mode is requested
        mode_setting = (account.get("mode") or "").strip().lower()
        env_use_browser = os.getenv("USE_BROWSER", "").strip().lower() in ("true", "1", "yes", "on")
        env_sign_mode = os.getenv("SIGN_MODE", "").strip().lower() in ("browser", "playwright")
        self.use_browser = mode_setting in ("browser", "playwright") or (
            mode_setting != "http" and (env_use_browser or env_sign_mode)
        )

        # Dynamic base URL resolution
        raw_base = (
            account.get("vercel_url")
            or account.get("proxy_url")
            or account.get("worker")
            or account.get("base_url")
            or os.getenv("VERCEL_PROXY_URL")
            or os.getenv("PROXY_URL")
            or os.getenv("CF_WORKER_URL")
            or os.getenv("BASE_URL")
            or DEFAULT_BASE_URL
        )
        self.base_url = normalize_base_url(raw_base)
        self.sign_page_url = f"{self.base_url}/k_misign-sign.html"
        self.sign_api_url = f"{self.base_url}/plugin.php?id=k_misign:sign&operation=qiandao"

        # Mount proxy if provided via account or environment
        proxy = account.get("proxy") or os.getenv("PROXY") or os.getenv("HTTPS_PROXY")
        if proxy and hasattr(self.session, "proxies") and isinstance(self.session.proxies, dict):
            self.session.proxies.update({
                "http": proxy,
                "https": proxy,
            })

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        custom_ua = self.account.get("user_agent") or os.getenv("USER_AGENT")
        if custom_ua:
            headers["User-Agent"] = custom_ua
        headers["Cookie"] = self.cookie
        # Referer should always be the standard target sign page
        headers["Referer"] = f"{DEFAULT_BASE_URL}/k_misign-sign.html"
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
            resp = getattr(exc, "response", None)
            status = getattr(resp, "status_code", None)
            if status == 403 and resp is not None:
                text = resp.text or ""
                cf_ray = resp.headers.get("cf-ray", "")
                if "Just a moment" in text or "challenges.cloudflare.com" in text or "cf-mitigated" in resp.headers or "__CF$cv$params" in text:
                    raise XsijisheAPIError(
                        f"请求司机社接口失败（HTTP 403 - 触发 Cloudflare 5秒盾/人机质询）\n"
                        f"   CF-Ray: {cf_ray or '无'}\n"
                        f"   💡 原因分析：目标站点 Cloudflare 开启了严格的人机安全验证（5秒盾）。\n"
                        f"   🔧 解决建议：\n"
                        f"      1. 确保抓取的 Cookie 中包含通过人机验证生成的 cf_clearance 字段\n"
                        f"      2. 确保请求的 User-Agent 与抓取 Cookie 时使用的浏览器一致（可在环境变量/Secrets 中设置 USER_AGENT）\n"
                        f"      3. 若在云端（GitHub Actions）运行，建议搭配住宅/国内代理（设置 PROXY）或配置自建 Runner"
                    ) from exc
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
        resp = self._request("GET", self.sign_page_url)
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

    @staticmethod
    def clean_sign_response(raw_text: str) -> str:
        """Clean and extract concise message from sign-in response."""
        cdata_match = re.search(r'<!\[CDATA\[([\s\S]*?)\]\]>', raw_text)
        msg = cdata_match.group(1) if cdata_match else raw_text
        clean = re.sub(r'<[^>]+>', ' ', msg)
        clean = ' '.join(clean.split())

        # Extract reward details: e.g. "签到成功 获得随机奖励 345车票 和 。 已累计签到 130 天。"
        reward_match = re.search(r'签到成功\s*获得(?:随机)?奖励\s*(\d+[^和。\s,，]*)', clean)
        if reward_match:
            reward_detail = reward_match.group(1).strip()
            total_match = re.search(r'已累计签到\s*(\d+)\s*天', clean)
            total_info = f"（已累计签到 {total_match.group(1)} 天）" if total_match else ""
            return f"签到成功，获得奖励：{reward_detail} {total_info}".strip()

        # Extract congratulations sentence
        congrats_match = re.search(r'(恭喜[^\n\r<>{}]*?签到成功[^\n\r<>{}]*)', clean)
        if congrats_match:
            return congrats_match.group(1).strip()

        if "今日已签" in clean or "已经签到" in clean:
            return "今日已完成签到"
        if "签到成功" in clean:
            return "签到成功"

        # If it's a short clean sentence (< 60 chars) without JS scripts
        if len(clean) < 60 and "var " not in clean and "function" not in clean:
            return clean

        return "签到请求已提交"

    def sign_in(self, formhash: str) -> str:
        """Perform sign-in request using formhash."""
        # Discuz! k_misign plugin AJAX sign-in endpoint
        ajax_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{DEFAULT_BASE_URL}/k_misign-sign.html",
        }

        # Try GET request first (the standard k_misign trigger)
        sign_url = f"{self.sign_api_url}&format=button&formhash={formhash}"
        resp = self._request("GET", sign_url, headers=ajax_headers)
        return self.clean_sign_response(resp.text)

    def do_sign_browser(self, wait_after_sign: float | None = None) -> str:
        """Execute sign-in using a headless browser to bypass Cloudflare Turnstile / 5s shield."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise XsijisheAPIError(
                "已启用无头浏览器模式，但未检测到 playwright 依赖。\n"
                "   🔧 解决方式：请执行 pip install playwright && playwright install chromium\n"
                "   💡 若在 GitHub Actions 中，请确认工作流安装了 playwright 及浏览器内核。"
            ) from exc

        if wait_after_sign is None:
            wait_env = os.getenv("SIGN_WAIT_SECONDS")
            wait_after_sign = float(wait_env) if wait_env else 3.0

        custom_ua = self.account.get("user_agent") or os.getenv("USER_AGENT") or DEFAULT_USER_AGENT
        proxy = self.account.get("proxy") or os.getenv("PROXY") or os.getenv("HTTPS_PROXY")
        proxy_settings = {"server": proxy} if proxy else None

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
        ]

        with sync_playwright() as p:
            browser = None
            launch_errors = []
            for launch_opts in [
                {"headless": True, "args": args},
                {"channel": "chrome", "headless": True, "args": args},
                {"channel": "msedge", "headless": True, "args": args},
            ]:
                if proxy_settings:
                    launch_opts["proxy"] = proxy_settings
                try:
                    browser = p.chromium.launch(**launch_opts)
                    break
                except Exception as exc:
                    launch_errors.append(str(exc))

            if not browser:
                err_detail = launch_errors[-1] if launch_errors else "未知启动异常"
                raise XsijisheAPIError(
                    f"无法启动浏览器内核，请确保已安装 Playwright 浏览器组件 (playwright install chromium)。\n"
                    f"   详细错误: {err_detail}"
                )

            try:
                context = browser.new_context(
                    user_agent=custom_ua,
                    viewport={"width": 1280, "height": 720},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

                # Inject cookies
                cookies_to_add = []
                for item in self.cookie.split(";"):
                    if "=" in item:
                        k, v = item.strip().split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        if k:
                            cookies_to_add.append({
                                "name": k,
                                "value": v,
                                "url": self.base_url,
                            })
                if cookies_to_add:
                    context.add_cookies(cookies_to_add)

                page = context.new_page()
                captured_sign_rewards: list[str] = []

                def handle_response(response):
                    try:
                        url_lower = response.url.lower()
                        if ("k_misign" in url_lower and "qiandao" in url_lower) or ("plugin.php" in url_lower and "sign" in url_lower and "qiandao" in url_lower):
                            resp_text = response.text()
                            clean_msg = Xsijishe.clean_sign_response(resp_text)
                            if clean_msg:
                                captured_sign_rewards.append(clean_msg)
                    except Exception:
                        pass

                page.on("response", handle_response)
                page.goto(self.sign_page_url, wait_until="load", timeout=60000)

                # Wait for Cloudflare Turnstile challenge completion and target elements
                try:
                    page.wait_for_selector(
                        "#JD_sign, .btnvisted, a.author, strong.vwmy, .nex_member, .qdleft",
                        timeout=25000,
                    )
                except Exception:
                    pass

                title = page.title()
                content = page.content()

                if "Just a moment" in title or "Attention Required" in title or "challenge-platform" in content:
                    time.sleep(5)
                    title = page.title()
                    content = page.content()
                    if "Just a moment" in title or "Attention Required" in title:
                        raise XsijisheAPIError(f"Cloudflare 人机质询未能自动通过 (页面标题: {title})")

                if "discuz_uid = '0'" in content or 'discuz_uid = "0"' in content:
                    raise XsijisheAPIError("账号 Cookie 已失效或未登录，请重新获取")

                jd_sign = page.locator("#JD_sign")
                btn_visted = page.locator(".btnvisted, .btn_haveread, .J_haveread")

                # Extract username
                username = self.user
                vwmy = page.locator("strong.vwmy a, a.author")
                if vwmy.count() > 0:
                    try:
                        nick = vwmy.first.inner_text(timeout=3000).strip()
                        if nick:
                            username = f"{self.user} ({nick})"
                    except Exception:
                        pass

                # Check if already signed today
                already_signed = False
                if btn_visted.count() > 0 or "今日已签" in content or "btnvisted" in content:
                    already_signed = True
                elif jd_sign.count() > 0:
                    try:
                        sign_text = jd_sign.first.inner_text(timeout=3000)
                    except Exception:
                        sign_text = ""
                    try:
                        sign_class = jd_sign.first.get_attribute("class", timeout=3000) or ""
                    except Exception:
                        sign_class = ""
                    if "今日已签" in sign_text or "haveread" in sign_class or "btnvisted" in sign_class or "signed" in sign_class:
                        already_signed = True
                elif page.locator("#lxdays, .qdleft, .qdright").count() > 0:
                    # In Discuz! k_misign plugin, #JD_sign is completely replaced by .btnvisted once signed
                    already_signed = True

                if already_signed:
                    status_line = "✅ 今日已签到，无需重复打卡"
                else:
                    if jd_sign.count() == 0:
                        raise XsijisheAPIError(f"未能在页面找到签到按钮 (页面标题: {title})")
                    sign_btn = jd_sign.first

                    clicked = False
                    try:
                        with page.expect_response(
                            lambda r: ("k_misign" in r.url.lower() and "qiandao" in r.url.lower())
                            or ("plugin.php" in r.url.lower() and "sign" in r.url.lower()),
                            timeout=8000,
                        ) as resp_info:
                            sign_btn.click(timeout=5000)
                            clicked = True
                        resp = resp_info.value
                        clean_msg = Xsijishe.clean_sign_response(resp.text())
                        if clean_msg:
                            captured_sign_rewards.append(clean_msg)
                    except Exception:
                        if not clicked:
                            try:
                                sign_btn.click(timeout=5000)
                            except Exception:
                                pass

                    if wait_after_sign > 0:
                        try:
                            page.wait_for_timeout(wait_after_sign * 1000)
                        except Exception:
                            time.sleep(wait_after_sign)

                    # Determine sign-in result safely without assuming #JD_sign still exists
                    if captured_sign_rewards:
                        status_line = f"🎉 签到结果：{captured_sign_rewards[-1]}"
                    else:
                        page_content_after = page.content()
                        visted_loc = page.locator(".btnvisted, .btn_haveread, .J_haveread")

                        visted_text = ""
                        if visted_loc.count() > 0:
                            try:
                                visted_text = visted_loc.first.inner_text(timeout=2000)
                            except Exception:
                                visted_text = ""

                        sign_text = ""
                        sign_class = ""
                        if jd_sign.count() > 0:
                            try:
                                sign_text = jd_sign.first.inner_text(timeout=2000)
                                sign_class = jd_sign.first.get_attribute("class", timeout=2000) or ""
                            except Exception:
                                sign_text = ""
                                sign_class = ""

                        if (
                            visted_loc.count() > 0
                            or "今日已签" in page_content_after
                            or "今日已签" in visted_text
                            or "今日已签" in sign_text
                            or "haveread" in sign_class
                            or "btnvisted" in sign_class
                            or "signed" in sign_class
                            or jd_sign.count() == 0  # Button was replaced/removed after sign-in
                        ):
                            status_line = "🎉 签到结果：签到成功"
                        elif sign_text:
                            clean_text = Xsijishe.clean_sign_response(sign_text)
                            status_line = f"🎉 签到结果：{clean_text or '签到请求已提交'}"
                        else:
                            status_line = "🎉 签到结果：签到请求已提交"

                # Extract check-in statistics
                stats = {}
                for stat_id in ("lxdays", "lxlevel", "lxreward", "lxtdays"):
                    loc = page.locator(f"#{stat_id}")
                    if loc.count() > 0:
                        try:
                            val = loc.first.get_attribute("value", timeout=2000)
                            if val is not None and val.strip():
                                stats[stat_id] = val.strip()
                        except Exception:
                            pass

                if not stats.get("lxdays"):
                    stats = self._parse_stats(page.content())

                lxdays = stats.get("lxdays") or "0"
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
            finally:
                browser.close()

    def do_sign(self, wait_after_sign: float | None = None) -> str:
        """Orchestrate the sign-in workflow for this account."""
        if self.use_browser:
            return self.do_sign_browser(wait_after_sign=wait_after_sign)

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
    skip_diagnostics: bool = False,
) -> int:
    """Run every configured account and return a process-compatible exit code."""
    print("----------司机社每日签到开始----------")

    if not skip_diagnostics:
        try:
            diag = check_network_connectivity()
            print("🌐 网络环境与连通性诊断:")
            print(f"🔗 访问模式     : {diag['access_mode']}")
            is_browser_env = (
                os.getenv("USE_BROWSER", "").strip().lower() in ("true", "1", "yes", "on")
                or os.getenv("SIGN_MODE", "").strip().lower() in ("browser", "playwright")
            )
            kernel_desc = "无头浏览器过盾模式 (Playwright)" if is_browser_env else "标准 HTTP 请求模式 (轻量)"
            print(f"⚙️ 签到内核     : {kernel_desc}")
            print(f"📍 本地出网 IP  : {diag['local_ip']}")
            print(f"🎯 目标站点解析: {diag['remote_ips']}")
            print(f"⚡ TCP 通信状态 : {diag['tcp_status']}")
            print(f"🛡️ HTTP 网关响应: {diag['gateway_status']}")
            print("----------------------------------------\n")
        except Exception as exc:
            print(f"⚠️ 网络环境诊断异常: {exc}\n")

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
