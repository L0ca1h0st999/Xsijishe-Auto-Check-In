# 🚗 司机社自动签到 (Xsijishe Auto Check-In)

通过 GitHub Actions 自动完成司机社论坛（Discuz! `k_misign` 米签到插件）每日打卡签到，获取每日金币/积分奖励，支持单账号与多账号，具备高稳定性、异常隔离、防风控随机休眠以及缓存幂等机制。

---

## 🚀 项目特性

- ⏰ **双定时调度与失败兜底**：北京时间每天 **08:30** 执行签到，**12:30** 进行失败自动重试兜底。
- ⚡️ **日期级幂等缓存**：当天所有账号签到成功后自动写入 GitHub Actions Cache，同一天内后续定时或重复触发自动跳过，节省 Actions 运行额度。
- 🌐 **网络诊断与 CF Worker 反代**：内置出网 IP、目标解析与 TCP/HTTP 网关全面诊断；支持配置免费 Cloudflare Worker 反向代理，彻底告别海外机房 IP 触发 403 拦截的问题。
- 👥 **完善的多账号支持**：支持 `\n`（换行）或 `&&` 分隔多账号；各账号独立执行，单个账号失败不会中断其他账号。
- 🛡 **动态安全令牌提取**：自动请求签到页解析动态 `formhash` CSRF 令牌，无需手动抓取与维护频繁过期的哈希值。
- 🎲 **防风控随机休眠**：定时任务触发时自动加入 0~60 秒随机延迟，请求携带现代主流浏览器 Client Hints，规避固定频次风控。
- 💓 **独立分支保活**：每月在独立的 `heartbeat` 分支生成空提交，避免 Fork 仓库因 60 天无活动被 GitHub 官方自动禁用定时任务，不污染 `main` 分支提交记录。

---

## 📋 使用方法

### 1. Fork 本仓库并启用 Actions

1. 点击本仓库右上角的 **Fork** 按钮。
2. 进入 Fork 后的仓库，点击 **Actions** 标签页。
3. 如果页面提示工作流未启用，点击 **"I understand my workflows, go ahead and enable them"**。

### 2. 获取登录 Cookie

在司机社论坛（`https://xsijishe.com`）完成登录后获取 Cookie：

#### 电脑端（推荐）
1. 在浏览器（Chrome / Edge 等）打开并登录 [司机社](https://xsijishe.com/)。
2. 按 `F12` 打开开发者工具，切换到 **Network（网络）** 标签页。
3. 刷新页面或访问 [签到页面](https://xsijishe.com/k_misign-sign.html)。
4. 在网络请求列表中点击任意 `xsijishe.com` 的请求（如 `k_misign-sign.html` 或页面主请求）。
5. 在右侧 **Headers（标头）** 中找到 **Request Headers（请求标头）** 下的 `Cookie`。
6. 复制整串 `Cookie` 内容即可（重点包含 `SgL6_2132_saltkey` 与 `SgL6_2132_auth`）。

> 💡 **提示**：直接复制浏览器中的整串 Cookie 即可，脚本会自动识别并正确传递。

---

### 3. 配置 GitHub Actions Secrets

进入你 Fork 的仓库，点击 **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**：

#### 必需变量：`COOKIE_XSIJISHE`
* **Name**: `COOKIE_XSIJISHE`
* **Secret**: 粘贴上一步获取的 Cookie 内容。

##### 账号配置格式说明
* **单账号（直接粘贴完整 Cookie）**：
  ```text
  SgL6_2132_saltkey=xxxxxx; SgL6_2132_auth=yyyyyy; ...
  ```
* **单账号（自定义昵称）**：
  ```text
  user=老司机张三; cookie=SgL6_2132_saltkey=xxxxxx; SgL6_2132_auth=yyyyyy; ...
  ```
* **多账号（换行或 `&&` 分隔）**：
  ```text
  user=张三; cookie=SgL6_...;
  user=李四; cookie=SgL6_...;
  ```

---

#### 强烈推荐：配置 Cloudflare Worker 反向代理（彻底规避 403）

由于 GitHub Actions 运行在微软 Azure 机房，目标站点启用的 Cloudflare WAF 会对数据中心 IP 触发“5秒盾”（HTTP 403）。配置免费的 Cloudflare Worker 可完美解决该问题：

##### 1. 创建 Worker（仅需 1 分钟）
1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/) -> 进入 **Workers & Pages** -> 点击 **Create Application** -> **Create Worker**。
2. 点击 **Deploy**，部署后点击 **Edit code**，清空原有代码并粘贴：
   ```javascript
   export default {
     async fetch(request) {
       const TARGET_HOST = "xsijishe.com";
       const url = new URL(request.url);
       const targetUrl = new URL(url.pathname + url.search, `https://${TARGET_HOST}`);
   
       const newHeaders = new Headers(request.headers);
       newHeaders.set("Host", TARGET_HOST);
       newHeaders.set("Origin", `https://${TARGET_HOST}`);
       if (newHeaders.has("Referer")) {
         newHeaders.set("Referer", newHeaders.get("Referer").replace(url.host, TARGET_HOST));
       }
   
       return fetch(new Request(targetUrl, {
         method: request.method,
         headers: newHeaders,
         body: request.body,
         redirect: "manual",
       }));
     }
   };
   ```
3. 点击 **Save and deploy**，获得你的专属链接，例如 `https://xsijishe-proxy.yourname.workers.dev`。

##### 2. 在 GitHub Secrets 中添加变量
* **Name**: `CF_WORKER_URL`
* **Secret**: 填写你的 Worker 地址（例如 `https://xsijishe-proxy.yourname.workers.dev`）

> 💡 **无需重新登录**：Discuz 账号鉴权 Cookie 与 IP 无关，Worker 出口是 Cloudflare 官方节点，不会触发 5 秒盾，因此直接使用您已有的 Cookie 即可！

---

### 4. 手动运行测试

1. 前往仓库的 **Actions** -> **司机社每日签到**。
2. 点击右侧 **Run workflow** -> 选择 `main` 分支启动。
3. 进入 Run 查看实时诊断与签到日志：
   - 会清晰展示访问模式（直连或 Worker 代理）、网络连通性及签到获得的连续天数与积分奖励！

---

## 🛠 本地运行与开发调试

克隆代码并进入项目目录：

```bash
git clone https://github.com/your-username/Xsijishe-Auto-Check-In.git
cd Xsijishe-Auto-Check-In
```

### 1. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### 2. 本地测试签到

在终端中设置环境变量并运行脚本：

```bash
# Windows PowerShell
$env:COOKIE_XSIJISHE = "user=我的账号; cookie=SgL6_2132_saltkey=...; SgL6_2132_auth=...;"
python checkIn_Xsijishe.py

# Linux / macOS
export COOKIE_XSIJISHE="user=我的账号; cookie=SgL6_2132_saltkey=...; SgL6_2132_auth=...;"
python checkIn_Xsijishe.py
```

### 3. 运行自动化测试

```bash
pytest -v
```

---

## ❓ 常见问题

### 1. 提示“账号 Cookie 已失效或未登录”
* Discuz! 的 `auth` 鉴权 Cookie 具有有效期或在用户修改密码/注销登录后会失效。
* 请重新在浏览器中登录论坛并抓取最新 Cookie 更新至 GitHub Secret。

### 2. 提示“无法从签到页面解析到 formhash”
* 请确认是否访问到了正常的论坛页面。如果触发了 Cloudflare 5秒盾或验证码拦截，可能需要稍后重试或更新 Cookie。

### 3. GitHub Actions 没有准点执行
* GitHub Actions 的 `schedule` 事件是由 GitHub 共享队列调度的，存在数分钟至几十分钟的队列排队延迟，这是平台正常特性。项目内置了 12:30 自动兜底重试以确保签到完成率。

---

## ⚠️ 免责声明

* 本项目仅供学习交流 Python 网络编程与自动化测试使用，请勿用于任何非法用途或对目标网站造成过量请求。
* 论坛接口可能会随官方版本升级而变更，如遇异常请提交 Issue。
* 本项目采用 [MIT License](LICENSE)。
