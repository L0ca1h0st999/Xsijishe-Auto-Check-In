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
    main,
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


if __name__ == "__main__":
    unittest.main()

