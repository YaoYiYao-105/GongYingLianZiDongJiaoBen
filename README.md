# 供应商后台箱码维护助手

> Supplier Portal Box-Code Automation — 把每天五分钟的重复点击交给程序

[![build-windows](https://github.com/YaoYiYao-105/GongYingLianZiDongJiaoBen/actions/workflows/build.yml/badge.svg)](https://github.com/YaoYiYao-105/GongYingLianZiDongJiaoBen/actions/workflows/build.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

---

## 这个项目解决什么问题

供应商后台的日常数据维护有一条固定链路，每天都要重复走一遍：

1. 在 UPI 维护页选择今日日期并查询
2. 从「下发的订单号」逐个进入订单明细
3. 在明细页点开「订货审批单」，进入箱码维护页
4. 在箱码维护页逐个点击每个商品的订货日期，输入箱码 `1`

整个过程大约五到六分钟。**它不算慢，但它极其枯燥** —— 而枯燥正是应该交给程序的那部分工作。

这个工具把这条链路压缩成「点一下按钮」。

---

## 快速开始

### 同事使用（不需要安装 Python）

1. 下载 `supplier-portal-automation-windows.zip` 并解压
2. 双击 `supplier-portal-automation.exe`
3. 首次使用点「登录」，在弹出的浏览器窗口里完成一次登录（可能需要短信验证）
4. 之后每天点「开始维护」即可

登录状态保存在本机专属的浏览器配置目录里，**只要不删掉那个目录，就不需要重复验证**。

### 开发者使用

```bash
git clone https://github.com/YaoYiYao-105/GongYingLianZiDongJiaoBen.git
cd GongYingLianZiDongJiaoBen
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
```

```bash
python main.py login                 # 一次性登录，登录态持久化保存
python main.py calibrate             # 采集真实页面结构（见下文）
python main.py run                   # 试运行：只列出将要处理的订单，不写任何数据
python main.py run --commit          # 正式执行
python main.py run --commit --limit 1        # 只处理第一个订单
python main.py run --commit --order 1234567  # 只处理指定订单
python main.py run --commit --mode browser   # 换回点击页面的方式
```

`--mode` 决定用哪种方式驱动后台，默认 `api`，两种方式的差别见下一节。

### 两种执行方式

同一个工作流有两套驱动方式，命令行用 `--mode` 切换，图形界面默认走 `api`。

| | `api`（默认） | `browser`（兜底） |
| --- | --- | --- |
| 原理 | 直接调用后台自己的 JSON 接口 | 打开页面、逐个单元格点击输入 |
| 耗时 | 秒级 | 分钟级 |
| 需要窗口 | 只在读取登录态时短暂打开一次 | 全程后台运行一个窗口 |
| 写后确认 | **重新拉取一遍数据，逐行核对箱码** | 依赖页面反馈 |
| 前端改版影响 | 接口不变就不受影响 | 定位器失效需要重新 `calibrate` |

`api` 模式复刻的是后台网页自己发出的那组请求：同样的地址、同样的请求体、同样的签名算法。
它不新建账号、不绕过权限，用的仍是**你自己浏览器里的那份登录态** ——
只是把「用鼠标点出来」换成了「直接把同样的请求发出去」。

**但是写入这件事不能只听服务端的回话。** 后台保存成功时返回 `200000`，但它不做逐行确认 ——
所以 `api` 模式在保存之后会**把订单重新读一遍**，逐行核对箱码和生产日期是否真的落库，
核对不上的行会被标成失败并出现在结果弹窗里。这是 `api` 模式能被放心交给同事的前提。

### 本地演示（不需要真实后台）

仓库自带一个模拟后台，可以在没有供应商账号的情况下完整跑通整条链路：

```bash
.venv/bin/python scripts/demo_local.py            # 试运行，不写入
.venv/bin/python scripts/demo_local.py --commit   # 实际写入模拟后台
```

它会启动一个复现了四个页面行为的本地 HTTP 服务，把定位配置指向它，然后运行**和正式版本完全相同的 workflow**。执行后会打印模拟后台收到的内容，用来确认结果：

```
mock portal state after the run:
  260917001: ['1', '1', '1', '1']
  260917002: ['1', '1', '1', '1']
  260917003: ['1', '1', '1', '1']
  submissions received: 3
RESULT: PASS
```

这是在不接触生产后台的前提下，验证"能不能真的把事做完"的最好方式。

---

## 为什么要先跑一次 `calibrate`（只影响点击模式）

**这一段只和 `--mode browser` 有关。** 默认的接口模式不使用任何元素定位器
（它走的是后台自己的 HTTP 接口），所以不需要标定，改版也不受影响。

仓库里自带的元素定位器是**基于公开信息的推断**，不是实测结果 —— 目标后台需要授权登录，开发阶段无法直接访问。
换句话说：**点击模式的定位器到目前为止仍是未经验证的占位值**，要用它就必须先标定一次。

```bash
python main.py calibrate
```

它会打开后台，等你在浏览器里登录、并手动走到箱码维护页，然后采集该页的真实 DOM 结构、可交互元素清单和截图，输出到 `runs/calibrate-<时间戳>/`。

**标定过程不输入任何内容、不提交任何表单。** 拿到清单后，把 `selectors.json` 里的定位器从"猜测"改成"确定"，之后就能稳定运行了。

---

## 工作原理

核心决策是把「做什么」和「在哪里做」彻底分开：业务模块只描述动作，所有元素定位集中在一个文件里。

```
main.py (CLI)  /  src/gui.py (双击运行的界面)
        │
        ▼
  src/workflow.py            选择用哪种方式驱动后台
        │
        ├── api_workflow.py       接口方式：查询 → 读明细 → 保存 → 读回核对
        │       └── api.py        签名、凭据、请求体
        │
        └── （点击方式）编排：查询 → 遍历订单 → 填箱码 → 记录
                ├── steps/upi_query.py    设置日期、查询、采集订单号
                ├── steps/order_flow.py   进入订单明细、打开订货审批单
                └── steps/box_code.py     遍历表格逐行填箱码
                        │
                        ▼
                  src/config.py      全部定位器集中在此
```

这样前端改版时，**只需要改定位器，不需要动业务逻辑**。

更完整的说明见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 配置

定位器存放在用户目录下的 `selectors.json`，首次运行自动生成，可以随时修改：

| 位置 | 路径 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\supplier-portal-automation\config\` |
| macOS | `~/Library/Application Support/supplier-portal-automation/config/` |
| Linux | `~/.local/share/supplier-portal-automation/config/` |

每个定位目标是一个**有序候选列表**，按顺序尝试，第一个命中的生效 —— 这样前端微调时不会立刻崩掉。

支持五种定位表达式：

| 表达式 | 含义 |
| --- | --- |
| `css=table tbody tr` | CSS 选择器 |
| `text=订货审批单` | 可见文本 |
| `role=button[name='查询']` | 无障碍角色 + 名称 |
| `placeholder=请选择日期` | 输入框占位符 |
| `label=箱码` | 表单标签 |

其他可调项：

```json
{
  "behavior": {
    "minimize_window": true,
    "box_code": 1
  },
  "timing": {
    "action_delay_ms": 450,
    "action_jitter_ms": 350,
    "nav_timeout_ms": 30000
  }
}
```

`minimize_window` 打开后，浏览器窗口会自动最小化到后台继续工作，你可以同时做别的事（程序本身也不会在运行中弹窗打扰，见下面「安全设计」）。

`box_code` 是要写入的箱码，默认为 `1`，两种方式都读这一项。

---

## 安全设计

这是要往生产后台写数据的工具，所以默认行为刻意偏向「什么都不做」：

- **默认试运行。** `run` 只遍历和报告，只有显式加上 `--commit` 才会真正写入。
- **幂等。** 点击方式下已经是 `1` 的行直接跳过；接口方式只处理仍处于「未执行」状态的订单，写完的订单会离开这个状态，重跑不会重复提交或覆盖。
- **失败就停，不猜。** 定位不到元素时标记该行失败并继续，**绝不"暴力点一下试试"** —— 在生产环境里，什么都没做远好过点错地方。
- **部分失败不提交。** 点击方式下只有整张表全部成功才会点保存；接口方式由服务端一次性写入，但写完会**逐行读回核对**，核对不上的行标记为失败。
- **可续跑。** 已完成的订单写入 JSONL 日志，中途中断可从断点继续。

失败时会在 `runs/<时间戳>/` 留下 `report.json` 与完整堆栈，点击方式还会留下截图和 HTML 快照，便于排查。

**失败会被明确告知，而不是悄悄结束。** 运行中止时汇总里打印的是

```
ABORTED — 页面上找不到预期的元素，前端可能已经改版，请重新运行「标定」更新定位配置。
```

而不是一行看起来像「今天没有订单」的空统计 —— 这一点很关键，因为后者会让人误以为跑完了。原始异常堆栈仍然完整写入 `runs/<时间戳>/run.log`，只是不往控制台刷屏。

**运行全程静默。** 点下「开始维护」之后，程序不会弹任何窗口、不会抢焦点、不会把界面提到最前 ——
接口方式下连浏览器都不会出现，界面上的日志只是滚动记录，你不看它也不影响任何事。

**只在最后弹一次窗。** 跑完（或中途停下）才弹出结果对话框：成功是提示框，失败是警告框，
写明失败在哪一步、下一步该做什么。窗口标题同时变成「完成」或「有失败项」，方便回来时从任务栏一眼确认。

弹窗期间窗口会临时置顶一次 —— 埋在最大化窗口后面的通知不叫通知 —— 弹窗一关就立刻取消置顶，
程序不会赖在别的窗口上面。

这是为「点一下就去干别的」设计的：中间不打扰你，结束时不让你错过结果。

---

## 登录态与浏览器

后台会把新设备判定为不可信并要求短信验证，因此**浏览器配置目录是关键资产**：

- 它持久化保存，位于用户目录而不是仓库里，程序不会删除它
- 导出登录 Cookie 的目录已被 `.gitignore` 排除

接口方式还需要用到登录态里的两个签名值，它们同样放在用户目录下的 `config\session.json`，
文件权限为 `600`。点过一次「登录」之后这两个值就会被缓存下来，**之后的日常维护根本不会打开浏览器窗口**；
只有缓存被服务端拒绝时，程序才会重新打开配置目录读取一次。

只有三种情况需要真的打开浏览器窗口：第一次点「登录」、缓存被服务端拒绝后重新读取登录态、以及使用点击模式。
真要用到浏览器时，程序优先驱动系统已安装的**品牌浏览器**，顺序为 Microsoft Edge（Windows 自带）→ Google Chrome →
Playwright 内置 Chromium。用真实浏览器既能降低被风控误判的概率，也让安装包小得多。

窗口最小化是安全的 —— Playwright 启动 Chromium 时已经关闭了后台定时器降频、渲染器降级和遮挡窗口降频。**少了这几个参数，窗口一最小化页面就会停止渲染、自动化直接卡死**，这是"切到后台就不动了"最常见的原因。

---

## 打包

PyInstaller 无法交叉编译，所以 Windows 可执行文件必须在 Windows 上产出。两种方式：

**GitHub Actions（自动）**

推送 `v*` 标签即自动构建并挂到 Releases：

```bash
git tag v0.1.0 && git push origin v0.1.0
```

**Windows 本地打包**

把项目拷到 Windows 机器，双击 `scripts\build_windows.bat`，产物在 `dist\supplier-portal-automation\`。

> 打包产物未做代码签名，Windows SmartScreen 首次运行时会提示。选择「更多信息 → 仍要运行」即可。

---

## 开发

```bash
.venv/bin/pip install pytest
.venv/bin/python -m playwright install chromium   # 仅端到端测试需要
.venv/bin/python -m pytest tests -q
```

共 115 个用例，全部只跑在本机、不访问外网，其中只有 3 个需要浏览器：

| 文件 | 用例 | 覆盖内容 | 需要浏览器 |
| --- | --- | --- | --- |
| `test_api.py` | 32 | 签名算法（逐字节钉死）、凭据解析、分页、箱码计划与核对 | 否 |
| `test_api_workflow.py` | 24 | 接口模式编排：读回校验、断点续跑、会话缓存、中止路径 | 否 |
| `test_workflow.py` | 12 | 点击模式编排流程、中止与退出码（状态机替身） | 否 |
| `test_errors.py` | 11 | 异常翻译成可读提示 | 否 |
| `test_gui.py` | 10 | 界面状态流转、结束通知、登录后缓存会话 | 否 |
| `test_config.py` | 9 | 定位表达式解析、角色参数校验 | 否 |
| `test_box_code.py` | 6 | 表格逐行遍历、跳过与失败统计 | 否 |
| `test_report.py` | 5 | 汇总统计与退出码 | 否 |
| `test_state.py` | 3 | 断点续跑日志 | 否 |
| `test_live_portal.py` | 3 | 真实 Chromium 驱动真实 HTTP 页面，断言服务端实际收到的数据 | **是** |

接口模式那两组完全不碰浏览器，也最容易回归：签名算法用一段固定的字节序列当基准，
改动其中任何一个字符都会直接失败，而不是等到线上才发现。

没有安装 Playwright 浏览器时，端到端测试会自动跳过而不是失败。

---

## 更新日志

变更记录见 [CHANGELOG.md](CHANGELOG.md)。

---

## License

[MIT](LICENSE)
