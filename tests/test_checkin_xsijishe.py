import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from checkIn_Xsijishe import (
    ConfigError,
    Xsijishe,
    XsijisheAPIError,
    get_access_mode_desc,
    main,
    normalize_base_url,
    parse_account,
    split_account_entries,
)


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.RequestException(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.proxies = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise RuntimeError("No more fake responses configured")
        return self.responses.pop(0)


class ParsingTests(unittest.TestCase):
    def test_split_accounts_empty_or_none(self):
        with self.assertRaises(ConfigError):
            split_account_entries(None)
        with self.assertRaises(ConfigError):
            split_account_entries("   \n   ")

    def test_split_accounts_supports_newlines_and_ampersand(self):
        entries = split_account_entries("acc1\nacc2&&acc3\r\nacc4")
        self.assertEqual(entries, ["acc1", "acc2", "acc3", "acc4"])

    def test_parse_account_key_value_format(self):
        entry = "user=老司机; cookie=SgL6_2132_saltkey=123; SgL6_2132_auth=456;"
        acc = parse_account(entry, 1)
        self.assertEqual(acc["user"], "老司机")
        self.assertIn("SgL6_2132_saltkey=123", acc["cookie"])
        self.assertIn("SgL6_2132_auth=456", acc["cookie"])

    def test_parse_account_raw_cookie_format(self):
        entry = "SgL6_2132_saltkey=abc; SgL6_2132_auth=def"
        acc = parse_account(entry, 2)
        self.assertEqual(acc["user"], "账号2")
        self.assertEqual(acc["cookie"], entry)

    def test_parse_account_inline_user(self):
        entry = "user=张三; SgL6_2132_saltkey=abc; SgL6_2132_auth=def"
        acc = parse_account(entry, 1)
        self.assertEqual(acc["user"], "张三")
        self.assertIn("SgL6_2132_auth=def", acc["cookie"])
        self.assertNotIn("user=", acc["cookie"])

    def test_parse_account_empty_raises(self):
        with self.assertRaises(ConfigError):
            parse_account("   ", 1)


class XsijisheWorkflowTests(unittest.TestCase):
    def test_not_logged_in_raises(self):
        html = """
        <html>
        <script>var discuz_uid = '0';</script>
        <a id="JD_sign" href="member.php?mod=logging&action=login"></a>
        </html>
        """
        session = FakeSession([FakeResponse(html)])
        client = Xsijishe({"user": "测试", "cookie": "dummy=1"}, session=session)
        with self.assertRaises(XsijisheAPIError) as ctx:
            client.get_sign_page()
        self.assertIn("Cookie 已失效或未登录", str(ctx.exception))

    def test_missing_formhash_raises(self):
        html = """
        <html>
        <script>var discuz_uid = '12345';</script>
        <div class="user"><a class="author">测试员</a></div>
        </html>
        """
        session = FakeSession([FakeResponse(html)])
        client = Xsijishe({"user": "测试", "cookie": "dummy=1"}, session=session)
        with self.assertRaises(XsijisheAPIError) as ctx:
            client.get_sign_page()
        self.assertIn("无法从签到页面解析到 formhash", str(ctx.exception))

    def test_already_signed_in(self):
        html = """
        <html>
        <script>var discuz_uid = '12345';</script>
        <input type="hidden" name="formhash" value="f68bd696" />
        <input type="hidden" id="lxdays" value="124" />
        <input type="hidden" id="lxlevel" value="5" />
        <input type="hidden" id="lxreward" value="10" />
        <input type="hidden" id="lxtdays" value="250" />
        <a id="JD_sign" class="btn J_chkitot J_haveread">今日已签到</a>
        <a class="author">老司机007</a>
        </html>
        """
        session = FakeSession([FakeResponse(html)])
        client = Xsijishe({"user": "账号1", "cookie": "dummy=1"}, session=session)
        result = client.do_sign()
        self.assertIn("连续签到：124 天", result)
        self.assertIn("签到等级：Lv.5", result)
        self.assertIn("积分奖励：+10", result)
        self.assertIn("总天数：250 天", result)
        self.assertIn("今日已签到，无需重复打卡", result)

    def test_not_signed_yet_signs_successfully(self):
        page_html = """
        <html>
        <script>var discuz_uid = '12345';</script>
        <input type="hidden" name="formhash" value="f68bd696" />
        <input type="hidden" id="lxdays" value="5" />
        <input type="hidden" id="lxlevel" value="2" />
        <input type="hidden" id="lxreward" value="1" />
        <input type="hidden" id="lxtdays" value="15" />
        <a id="JD_sign" class="btn J_chkitot">点击签到</a>
        <a class="author">老司机007</a>
        </html>
        """
        sign_resp_xml = """<?xml version="1.0" encoding="utf-8"?>
        <root><![CDATA[恭喜您签到成功！获得金币 +2]]></root>
        """
        updated_page_html = """
        <html>
        <script>var discuz_uid = '12345';</script>
        <input type="hidden" name="formhash" value="f68bd696" />
        <input type="hidden" id="lxdays" value="6" />
        <input type="hidden" id="lxlevel" value="2" />
        <input type="hidden" id="lxreward" value="2" />
        <input type="hidden" id="lxtdays" value="16" />
        <a id="JD_sign" class="btn J_chkitot J_haveread">今日已签到</a>
        <a class="author">老司机007</a>
        </html>
        """
        session = FakeSession([
            FakeResponse(page_html),
            FakeResponse(sign_resp_xml),
            FakeResponse(updated_page_html),
        ])
        client = Xsijishe({"user": "账号1", "cookie": "dummy=1"}, session=session)
        result = client.do_sign(wait_after_sign=0)
        self.assertIn("连续签到：6 天", result)
        self.assertIn("签到等级：Lv.2", result)
        self.assertIn("积分奖励：+2", result)
        self.assertIn("总天数：16 天", result)
        self.assertIn("签到结果：恭喜您签到成功！获得金币 +2", result)
        self.assertEqual(len(session.calls), 3)
        # Check that formhash was passed in the sign API call
        self.assertIn("formhash=f68bd696", session.calls[1][1])


    def test_parse_account_with_proxy(self):
        entry = "user=老司机; cookie=SgL6_2132_auth=123; proxy=http://127.0.0.1:7890;"
        acc = parse_account(entry, 1)
        self.assertEqual(acc["user"], "老司机")
        self.assertEqual(acc["proxy"], "http://127.0.0.1:7890")
        self.assertIn("SgL6_2132_auth=123", acc["cookie"])
        self.assertNotIn("proxy=", acc["cookie"])

    def test_parse_account_with_worker(self):
        entry = "user=老司机; cookie=SgL6_2132_auth=123; worker=https://xsijishe.workers.dev/;"
        acc = parse_account(entry, 1)
        self.assertEqual(acc["user"], "老司机")
        self.assertEqual(acc["worker"], "https://xsijishe.workers.dev/")
        self.assertIn("SgL6_2132_auth=123", acc["cookie"])
        self.assertNotIn("worker=", acc["cookie"])

    def test_clean_sign_response_with_html_noise(self):
        noisy_html = (
            "<html><body><script>var x=1;</script><div>"
            "已签到 连续125天 1202人 1197 签到成功 获得随机奖励 345车票 和 。 已累计签到 130 天。"
            "</div><script>jQuery(function(){});</script></body></html>"
        )
        msg = Xsijishe.clean_sign_response(noisy_html)
        self.assertEqual(msg, "签到成功，获得奖励：345车票 （已累计签到 130 天）")

    def test_worker_base_url_customization(self):
        client = Xsijishe({"user": "测试", "cookie": "a=1", "worker": "https://custom.workers.dev/"})
        self.assertEqual(client.base_url, "https://custom.workers.dev")
        self.assertEqual(client.sign_page_url, "https://custom.workers.dev/k_misign-sign.html")
        self.assertEqual(client.sign_api_url, "https://custom.workers.dev/plugin.php?id=k_misign:sign&operation=qiandao")

    def test_normalize_base_url_various_formats(self):
        self.assertEqual(
            normalize_base_url("https://xsijishe-proxy-vercel.vercel.app/k_misign-sign.html"),
            "https://xsijishe-proxy-vercel.vercel.app",
        )
        self.assertEqual(
            normalize_base_url("https://xsijishe-proxy-vercel.vercel.app/"),
            "https://xsijishe-proxy-vercel.vercel.app",
        )
        self.assertEqual(
            normalize_base_url("xsijishe-proxy-vercel.vercel.app"),
            "https://xsijishe-proxy-vercel.vercel.app",
        )
        self.assertEqual(
            normalize_base_url(""),
            "https://xsijishe.com",
        )
        self.assertEqual(
            normalize_base_url(None),
            "https://xsijishe.com",
        )

    def test_get_access_mode_desc(self):
        self.assertIn("Vercel 反向代理", get_access_mode_desc("https://demo.vercel.app"))
        self.assertIn("Cloudflare Worker 反代", get_access_mode_desc("https://demo.workers.dev"))
        self.assertIn("反向代理", get_access_mode_desc("https://proxy.custom.com"))
        self.assertIn("直连目标站点", get_access_mode_desc("https://xsijishe.com"))

    def test_parse_account_with_vercel_url(self):
        entry = "user=老司机; cookie=SgL6_2132_auth=123; vercel_url=https://xsijishe-proxy-vercel.vercel.app/k_misign-sign.html;"
        acc = parse_account(entry, 1)
        self.assertEqual(acc["user"], "老司机")
        self.assertEqual(acc["vercel_url"], "https://xsijishe-proxy-vercel.vercel.app/k_misign-sign.html")
        self.assertIn("SgL6_2132_auth=123", acc["cookie"])
        self.assertNotIn("vercel_url=", acc["cookie"])

    def test_parse_account_with_user_agent(self):
        entry = "user=老司机; cookie=SgL6_2132_auth=123; ua=Mozilla/5.0 (CustomBrowser);"
        acc = parse_account(entry, 1)
        self.assertEqual(acc["user"], "老司机")
        self.assertEqual(acc["user_agent"], "Mozilla/5.0 (CustomBrowser)")
        self.assertIn("SgL6_2132_auth=123", acc["cookie"])
        self.assertNotIn("ua=", acc["cookie"])

        client = Xsijishe(acc)
        headers = client._headers()
        self.assertEqual(headers["User-Agent"], "Mozilla/5.0 (CustomBrowser)")

    def test_proxy_environment_does_not_break_fake_session(self):
        old_proxy = os.environ.get("HTTPS_PROXY")
        try:
            os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9999"
            session = FakeSession([FakeResponse("<html></html>")])
            client = Xsijishe({"user": "测试", "cookie": "a=1"}, session=session)
            self.assertEqual(session.proxies.get("https"), "http://127.0.0.1:9999")
        finally:
            if old_proxy is not None:
                os.environ["HTTPS_PROXY"] = old_proxy
            else:
                os.environ.pop("HTTPS_PROXY", None)

    def test_parse_account_with_mode(self):
        entry = "user=老司机; cookie=SgL6_2132_auth=123; mode=browser;"
        acc = parse_account(entry, 1)
        self.assertEqual(acc["user"], "老司机")
        self.assertEqual(acc["mode"], "browser")
        self.assertIn("SgL6_2132_auth=123", acc["cookie"])
        self.assertNotIn("mode=", acc["cookie"])

    def test_browser_mode_resolution(self):
        # Default is False
        c1 = Xsijishe({"user": "测试", "cookie": "a=1"})
        self.assertFalse(c1.use_browser)

        # Account mode=browser
        c2 = Xsijishe({"user": "测试", "cookie": "a=1", "mode": "browser"})
        self.assertTrue(c2.use_browser)

        # USE_BROWSER=true env
        with unittest.mock.patch.dict(os.environ, {"USE_BROWSER": "true"}):
            c3 = Xsijishe({"user": "测试", "cookie": "a=1"})
            self.assertTrue(c3.use_browser)

            # Account mode=http overrides env
            c4 = Xsijishe({"user": "测试", "cookie": "a=1", "mode": "http"})
            self.assertFalse(c4.use_browser)

        # SIGN_MODE=browser env
        with unittest.mock.patch.dict(os.environ, {"SIGN_MODE": "browser"}):
            c5 = Xsijishe({"user": "测试", "cookie": "a=1"})
            self.assertTrue(c5.use_browser)

    def test_browser_mode_missing_playwright_raises(self):
        client = Xsijishe({"user": "测试", "cookie": "a=1", "mode": "browser"})
        with unittest.mock.patch.dict(sys.modules, {"playwright.sync_api": None}):
            with self.assertRaises(XsijisheAPIError) as ctx:
                client.do_sign_browser()
            self.assertIn("未检测到 playwright 依赖", str(ctx.exception))


class MainIntegrationTests(unittest.TestCase):
    def test_main_all_success(self):
        class MockClient:
            def __init__(self, account):
                self.account = account

            def do_sign(self):
                return "✅ 签到成功"

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main("user=A; cookie=123 && user=B; cookie=456", client_factory=MockClient, skip_diagnostics=True)
        self.assertEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("成功 2，失败 0", output)

    def test_main_partial_failure(self):
        calls = 0

        def factory(account):
            nonlocal calls
            calls += 1
            mock = MagicMock()
            if calls == 1:
                mock.do_sign.side_effect = XsijisheAPIError("凭据已失效")
            else:
                mock.do_sign.return_value = "✅ 签到成功"
            return mock

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main("user=A; cookie=123\nuser=B; cookie=456", client_factory=factory, skip_diagnostics=True)
        self.assertEqual(code, 1)
        output = buf.getvalue()
        self.assertIn("成功 1，失败 1", output)

    def test_main_diagnostics_output(self):
        buf = io.StringIO()
        with unittest.mock.patch("checkIn_Xsijishe.check_network_connectivity") as mock_diag:
            mock_diag.return_value = {
                "access_mode": "直连目标站点 (https://xsijishe.com)",
                "local_ip": "1.1.1.1",
                "remote_ips": "104.21.85.91",
                "tcp_status": "正常 (握手延迟: 20ms)",
                "gateway_status": "HTTP 200 正常",
            }

            class MockClient:
                def __init__(self, account):
                    pass

                def do_sign(self):
                    return "✅ 签到成功"

            with redirect_stdout(buf):
                with unittest.mock.patch.dict(os.environ, {"USE_BROWSER": "true"}):
                    main("user=A; cookie=123", client_factory=MockClient, skip_diagnostics=False)
            output = buf.getvalue()
            self.assertIn("网络环境与连通性诊断", output)
            self.assertIn("无头浏览器过盾模式 (Playwright)", output)


if __name__ == "__main__":
    unittest.main()

