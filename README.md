# 🚗 司机社自动签到 (Xsijishe Auto Check-In)

通过 GitHub Actions 自动完成司机社论坛（Discuz! `k_misign` 米签到插件）每日打卡签到，获取每日金币/积分奖励，支持单账号与多账号。

架构与设计借鉴自 [Quark_Auto_Check_In](https://github.com/Liu8Can/Quark_Auot_Check_In)，具备高稳定性、异常隔离、防风控随机休眠以及缓存幂等机制。

---

## 🚀 项目特性

- ⏰ **双定时调度与失败兜底**：北京时间每天 **08:30** 执行签到，**12:30** 进行失败自动重试兜底。
- ⚡️ **日期级幂等缓存**：当天所有账号签到成功后自动写入 GitHub Actions Cache，同一天内后续定时或重复触发自动跳过，节省 Actions 运行额度。
- 👥 **完善的多账号支持**：支持 `\n`（换行）或 `&&` 分隔多账号；各账号独立执行，单个账号失败不会中断其他账号。
- 🛡 **动态安全令牌提取**：自动请求签到页解析动态 `formhash` CSRF 令牌，无需手动抓取与维护频繁过期的哈希值。
- 🎲 **防风控随机休眠**：定时任务触发时自动加入 0~60 秒随机延迟，请求携带现代主流浏览器 User-Agent，规避固定频次风控。
- 💓 **独立分支保活**：每月在独立的 `heartbeat` 分支生成空提交，避免 Fork 仓库因 60 天无活动被 GitHub 官方自动禁用定时任务，不污染 `main` 分支提交记录。

---

## 📋 使用方法

### 1. Fork 本仓库并启用 Actions

1. 点击本仓库右上角的 **Fork** 按钮。
2. 进入 Fork 后的仓库，点击 **Actions** 标签页。
3. 如果页面提示工作流未启用，点击 **"I understand my workflows, go ahead and enable them"**。

### 2. 获取登录 Cookie

在小司机社论坛（`https://xsijishe.com`）完成登录后获取 Cookie：

#### 电脑端（推荐）
1. 在浏览器（Chrome / Edge 等）打开并登录 [小司机社](https://xsijishe.com/)。
2. 按 `F12` 打开开发者工具，切换到 **Network（网络）** 标签页。
3. 刷新页面或访问 [签到页面](https://xsijishe.com/k_misign-sign.html)。
4. 在网络请求列表中点击任意 `xsijishe.com` 的请求（如 `k_misign-sign.html` 或页面主请求）。
5. 在右侧 **Headers（标头）** 中找到 **Request Headers（请求标头）** 下的 `Cookie`。
6. 复制整串 `Cookie` 内容即可（重点包含 `SgL6_2132_saltkey` 与 `SgL6_2132_auth`）。

> 💡 **提示**：直接复制浏览器中的整串 Cookie 即可，脚本会自动识别并正确传递，无需手动挑选字段。

---

### 3. 配置 GitHub Actions Secret

1. 进入你 Fork 的仓库，点击 **Settings** -> **Secrets and variables** -> **Actions**。
2. 点击 **New repository secret** 按钮添加密钥：
   - **Name**: `COOKIE_XSIJISHE`
   - **Secret**: 粘贴上一步获取的 Cookie 内容。

#### 账号配置格式说明

##### 单账号格式（两种均支持）
* **直接粘贴完整 Cookie**：
  ```text
  SgL6_2132_saltkey=xxxxxx; SgL6_2132_auth=yyyyyy; ...
  ```
* **自定义昵称（推荐）**：
  ```text
  user=老司机张三; cookie=SgL6_2132_saltkey=xxxxxx; SgL6_2132_auth=yyyyyy; ...
  ```

##### 多账号格式
支持使用**换行**或 `&&` 分隔多个账号：

* **换行分隔**：
  ```text
  user=张三; cookie=SgL6_2132_saltkey=...; SgL6_2132_auth=...;
  user=李四; cookie=SgL6_2132_saltkey=...; SgL6_2132_auth=...;
  ```
* **`&&` 分隔**：
  ```text
  user=张三; cookie=SgL6_...; && user=李四; cookie=SgL6_...;
  ```

---

### 4. 手动运行测试

1. 前往仓库的 **Actions** -> **司机社每日签到**。
2. 点击右侧 **Run workflow** -> 选择 `main` 分支并点击绿色按钮启动。
3. 点击进入正在运行的 Run 查看日志：
   - 首次运行会真实发起签到，并输出各账号连续签到天数及签到结果；
   - 若当天已成功签到，再次运行时会显示：“今日已全部签到成功，跳过重复执行。”

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
