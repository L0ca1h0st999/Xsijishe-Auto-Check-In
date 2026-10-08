# 司机社自动签到 (Xsijishe Auto Check-In)

基于 Python 与 GitHub Actions 的司机社论坛（Discuz! `k_misign` 插件）自动化打卡签到工具。支持单账号与多账号，内置网络诊断、Vercel 反向代理支持、异常隔离、防风控随机休眠与缓存幂等机制。

---

## 功能特性

- **双定时调度与失败兜底**：北京时间每天 08:30 执行签到，12:30 自动重试兜底。
- **日期级幂等缓存**：当天账号全部签到成功后自动写入 GitHub Actions Cache，同一天内后续定时或重复触发自动跳过，节省 Actions 运行额度。
- **Vercel 反向代理支持**：针对 GitHub Actions 云机房 IP 触发 Cloudflare 5秒盾（HTTP 403）的问题，原生支持 Vercel 免费反代，实现稳定通信。
- **网络诊断与健康检查**：内置出网 IP、目标 DNS 解析、TCP 延迟与 HTTP 网关响应诊断，便于排查环境问题。
- **多账号与独立隔离**：支持换行或 `&&` 分隔多账号配置，各账号独立执行，单账号异常不影响其他账号。
- **动态令牌自动提取**：自动从签到页面提取动态 `formhash` CSRF 令牌，无需手动抓取与维护。
- **防风控随机延迟**：定时执行时自动加入 0~60 秒随机延迟，并附带主流浏览器 Client Hints 请求头。
- **仓库自动保活机制**：每月在独立的 `heartbeat` 分支生成空提交，防止 GitHub 官方因仓库 60 天无活动自动停用定时任务。

---

## 快速开始

### 1. Fork 本仓库并启用 Actions

1. 点击本仓库右上角 **Fork** 按钮。
2. 进入 Fork 后的仓库，切换到 **Actions** 页面。
3. 若提示工作流未启用，点击 **"I understand my workflows, go ahead and enable them"**。

### 2. 部署 Vercel 反向代理（推荐，解决 Actions 403）

由于 GitHub Actions 运行在微软 Azure 机房，目标站点启用的 Cloudflare 防护会对机房 IP 触发人机验证（HTTP 403）。使用 Vercel 免费部署一个轻量反向代理即可彻底解决此问题。

#### 部署步骤（仅需 1 分钟）
1. 在 GitHub 上新建一个仓库（例如 `xsijishe-proxy`，建议设为 Private）。
2. 在该仓库根目录下新建文件 `vercel.json`，内容如下：
   ```json
   {
     "rewrites": [
       {
         "source": "/:path*",
         "destination": "https://xsijishe.com/:path*"
       }
     ]
   }
   ```
3. 登录 [Vercel 官网 (vercel.com)](https://vercel.com)，点击 **Add New...** -> **Project**。
4. 导入刚刚创建的 `xsijishe-proxy` 仓库，Framework Preset 保持默认（Other），点击 **Deploy**。
5. 部署完成后即可获得专属域名，例如 `https://xsijishe-proxy-xxxx.vercel.app`。

### 3. 获取论坛登录 Cookie

在电脑端浏览器中登录司机社论坛（`https://xsijishe.com`）后获取 Cookie：

1. 打开浏览器登录 [司机社](https://xsijishe.com/)。
2. 按 `F12` 打开开发者工具，切换到 **Network（网络）** 标签页。
3. 刷新页面或访问 [签到页面](https://xsijishe.com/k_misign-sign.html)。
4. 在网络请求列表中点击任意 `xsijishe.com` 请求（如 `k_misign-sign.html`）。
5. 在 **Headers（标头）** -> **Request Headers（请求标头）** 中找到 `Cookie`。
6. 复制整串 `Cookie` 内容（需包含 `SgL6_2132_saltkey` 与 `SgL6_2132_auth` 字段）。

### 4. 配置 GitHub Actions Secrets

进入 Fork 仓库，点击 **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**：

| Secret 名称 | 是否必需 | 说明 |
| :--- | :--- | :--- |
| `COOKIE_XSIJISHE` | **必需** | 用户的论坛登录 Cookie |
| `VERCEL_PROXY_URL` | **推荐** | 第 2 步中部署的 Vercel 域名（如 `https://xxx.vercel.app`） |
| `PROXY` | 可选 | 自定义 HTTP/SOCKS5 代理地址（如 `http://1.2.3.4:7890`） |

#### COOKIE_XSIJISHE 配置格式

- **单账号（直接粘贴完整 Cookie）**：
  ```text
  SgL6_2132_saltkey=xxxxxx; SgL6_2132_auth=yyyyyy; ...
  ```

- **单账号（自定义昵称）**：
  ```text
  user=老司机张三; cookie=SgL6_2132_saltkey=xxxxxx; SgL6_2132_auth=yyyyyy; ...
  ```

- **多账号（换行或 `&&` 分隔）**：
  ```text
  user=张三; cookie=SgL6_...;
  user=李四; cookie=SgL6_...;
  ```

### 5. 手动运行测试

1. 前往仓库的 **Actions** -> **司机社每日签到**。
2. 点击 **Run workflow** -> 选择 `main` 分支启动。
3. 查看执行日志，确认网络诊断、访问模式及签到结果（连续签到天数、等级、积分奖励等）。

---

## 本地运行与开发调试

### 1. 安装依赖

```bash
git clone https://github.com/your-username/Xsijishe-Auto-Check-In.git
cd Xsijishe-Auto-Check-In

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### 2. 本地执行

```bash
# Windows PowerShell
$env:COOKIE_XSIJISHE = "user=我的账号; cookie=SgL6_2132_saltkey=...; SgL6_2132_auth=...;"
python checkIn_Xsijishe.py

# Linux / macOS
export COOKIE_XSIJISHE="user=我的账号; cookie=SgL6_2132_saltkey=...; SgL6_2132_auth=...;"
python checkIn_Xsijishe.py
```

### 3. 运行单元测试

```bash
pytest -v
```

---

## 常见问题

### 1. 提示“账号 Cookie 已失效或未登录”
Discuz! 的鉴权 Cookie 在密码修改、账号注销或到期后会失效。请重新在浏览器登录并抓取最新 Cookie 更新至 GitHub Secret。

### 2. 提示“HTTP 403 - 触发 Cloudflare 5秒盾/人机质询”
GitHub Actions 的云机房 IP 被目标站的 Cloudflare WAF 策略拦截。请按照文档第 2 步配置免费的 `VERCEL_PROXY_URL` 反向代理即可解决。

### 3. GitHub Actions 没有准点执行
GitHub Actions 的定时触发任务受全局队列调度影响，通常会有数分钟至数十分钟的排队延迟，属平台正常现象。本项目已配置 12:30 自动兜底重试以保障签到成功率。

---

## 免责声明

- 本项目仅供 Python 网络编程与自动化测试技术交流使用，请勿用于商业目的或对目标站点发起过载请求。
- 目标论坛接口如发生升级变更，欢迎提交 Issue 或 Pull Request。
- 本项目遵循 [MIT License](LICENSE)。
