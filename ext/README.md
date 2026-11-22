# Clawd-Mochi 扩展 hook 实验包

> 结论先说：**能加，而且限制不在"hook"这一层。**
> hook 的本质只是"AI 工具在某个事件上执行一条命令"，命令里干什么都行。
> 真正的边界是中间那层 `Clawd-Mochi.exe` 的桥接：它只认 7 个状态名（18892 端口），
> 而设备本身懂 13 个事件名，还额外暴露了终端文字、画布、背景色、动画速度、背光、
> 自定义图片等接口。所以想做"更多功能"，只要让 hook 绕过桥接直接调设备即可。

本目录是围绕这台机器实测出来的可运行原型 + 结论记录。

### 端口 / 地址速查（别搞混）

| 地址 | 是什么 | 能打开的东西 |
| --- | --- | --- |
| `http://127.0.0.1:18893/` | 控制中心网页（官方） | 就是那个设置/图片/动画测试页面。**没有 `/status` 路径**，访问 `/status` 会返回 `{"ok":false,"error":"not found"}`，这是正常的 |
| `http://127.0.0.1:18893/api/status` | 控制中心的状态 JSON（官方） | 已启用的平台、设备状态 |
| `http://127.0.0.1:18892/event?s=<状态>` | 官方桥的事件入口（只收 GET，7 个状态名） | 只能发事件，不是页面 |
| `http://127.0.0.1:18895/` | **本包的 CS2 状态页** | 网页面板：桥/桌宠/GSI 是否在线、击杀死亡、8 个测试按钮 |
| `http://127.0.0.1:18895/status` | CS2 桥的状态 JSON | 给程序读的那份 |
| `http://clawd-mochi.local/` | 桌宠设备自带网页 | 换脸/打字/画布/背光/自定义图片 |

`18895` 这个端口是本包新加的（`cs2_mochi.py`），**不跑它就没有页面**——它和官方控制中心是两个独立进程。

---

## 1. 三层边界（实测）

| 层 | 位置 | 接受什么 | 实测证据 |
| --- | --- | --- | --- |
| AI 工具侧 hook | 各家配置（`.claude/settings.json`、`.codex/hooks.json`…） | **任意命令** | 控制中心写进去的就是 `powershell.exe -EncodedCommand <base64>`，解码后只是一次 `Invoke-WebRequest http://127.0.0.1:18892/event?s=<state>` |
| 桥接层 | `Clawd-Mochi.exe` 监听 `127.0.0.1:18892`（事件）+ `18893`（网页控制台） | 只有 7 个名字：`idle thinking coding waiting done error sleep`；只支持 `GET /event?s=`；没有 POST/JSON | `?s=idle` → 204；`?s=planning` → 400；`?s=notify` → 400；`/event` 无参数 → 400；`/` → 404 |
| 设备侧（Wi-Fi 版） | `http://clawd-mochi.local` | 13 个事件名 + 一整套 HTTP 接口 | `/event?s=reading`、`?s=planning`、甚至 `?s=bogus` 都返回 200（设备静默忽略未知名）；`/state`、`/char`、`/cmd`、`/speed`、`/backlight`、`/redraw`、`/canvas`、`/draw/*`、`/image/*` 全部可用 |

设备 `/state` 返回：`{"view":0,"busy":false,"term":false,"bl":true,"speed":1,"sta":true,"ssid":"..."}`
`view`：0 普通眼 / 1 眯眼 / 2 终端（Claude Code 界面）/ 3 画布。

### 设备能力的真实含义

| 接口 | 干什么 | 能挂出什么新功能 |
| --- | --- | --- |
| `/cmd?k=w` / `s` / `d` / `q` | 普通眼 / 眯眼(休息) / 终端视图 / 关终端 | 手动切"休息中" |
| `/char?c=<字符>`（`%0A` 换行、`%08` 退格） | **在终端视图里逐字符打字** | 把"正在跑哪个工具/哪条命令/哪个模型/花了多少钱"真的显示在屏幕上 |
| `/speed?v=1|2|3` | 表情动画速度（慢/正常/快） | 用速度表达紧急度 / 卡住 |
| `/backlight?on=0|1` | 背光 | 夜间自动熄灯、只在需要你时亮屏 |
| `/redraw?bg=RRGGBB` | 非画布模式下换底色 | 用颜色区分项目 / 模型 / 成功失败 |
| `/canvas?on=1` + `/draw/clear?bg=` + `/draw/stroke?pen=RRGGBB&pts=x,y;…` | 进入 240×180 画布，按点画线 | 进度条（上下文用量、任务完成度）、简易图表、像素画、倒计时 |
| `/images`、`/image/upload`、`/image/reset?state=0..6` | 给 7 个状态各上传一张 240×180 RGB 自定义图 | **不改固件就"换一套皮肤/新画面"** |

注意：终端视图和画布视图是"独占"的——进入后表情动画停止，退出才恢复；`/canvas?on=1` 实测要 ~2.8 s。

---

## 2. 能加什么（按投入排序）

### A. 零代码：给已支持平台加"更多事件"

控制中心给 Claude Code 只挂了 9 个事件，还剩 `Notification`、`PreCompact`、`PostCompact`、`SubagentStart`、`SubagentStop` 没挂。加进去就能多出两种真实状态：

- `Notification` → `waiting`：Claude 需要你注意（不只是权限请求，也包括"我闲着等你说话"）。
- `PreCompact` → `compacting`：上下文压缩开始时提醒一次。

同理：Cursor / Trae / Qoder / Codex / Gemini 各自的 hooks 配置文件里都能再塞事件或换 `matcher`（现在控制中心统一用 `"*"`，可以改成只在你关心的工具上触发，比如只给 `Bash` 挂 `PreToolUse`，减少噪音）。

示例见 `examples/claude-code-extra-hooks.json`。

### B. 零代码但有技术含量：把 hook 命令换成 `curl.exe`

控制中心生成的命令是每次启动一个 PowerShell（实测 **630–770 ms/次**，冷启动 3.8 s）。
`curl.exe` 是 Windows 自带的，同样一次 HTTP 只要 **33–55 ms**（约 15 倍快）。
一次工具调用通常触发 `PreToolUse` + `PostToolUse` 两个 hook，等于每次工具调用省下 ~1.3 s。

```jsonc
// 把这种：
"command": "powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand JABDAGwA…"
// 换成这种：
"command": "C:\\Windows\\System32\\curl.exe -s -o NUL --max-time 2 \"http://127.0.0.1:18892/event?s=coding\""
```

### C. 本包提供的"扩展桥"（`mochi_bridge.py`，18894 端口）

hook 只发一条 HTTP，桥接负责把"事件 + 文本/进度/颜色"翻译成设备动作，并且**保留原来的表情动画**：

```bash
python ext/mochi_bridge.py                 # 只做 背景色/速度/背光/13 事件
python ext/mochi_bridge.py --terminal      # 允许把文字打到设备终端视图
python ext/mochi_bridge.py --canvas        # 允许把进度画到设备画布
python ext/mochi_bridge.py --no-stock      # 完全接管，不再喂 18892
```

hook 侧（任何平台、任何脚本）：

```bash
python ext/mochi_hook.py coding --text "Bash: npm test"
python ext/mochi_hook.py coding --stdin tool_name     # 直接吃 Claude Code 的 stdin JSON
python ext/mochi_hook.py waiting --text "等确认: rm -rf build"
python ext/mochi_hook.py coding --progress 0.42        # 画进度条（需 --canvas）
python ext/mochi_hook.py idle --bg 101820 --speed 1 --bl 0
```

`mochi_hook.py` 全程 ≤1.2 s 预算、失败静默、永远 `exit 0`（很多工具会因为 PreToolUse hook 非零退出而中断工具调用）。

### D. 给 DeepSeek Harness 换更细的插件

`ext/dsh-plugin/index.js` 是控制中心自带 `deepseek_plugin/index.js` 的增强版：除了原来的 5 个状态，还转发 `tool/call` 的工具名+参数、`approval/asked` 的命令内容、`approval/decided` 的 rejected、子 Agent 生命周期，桥挂掉时自动回落 18892。

把它挂进 `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml`：

```yaml
- id: clawd-mochi-status
  name: <repo>/ext/dsh-plugin/index.js
  config:
    executable: D:/Program Files (x86)/Clawd-Mochi-Windows/Clawd-Mochi.exe
```

（改完重启 DSH；想回退就指回 `%APPDATA%\ClawdMochi/deepseek_plugin/index.js`。）
注意：DSH 插件是常驻 JS，本身 **~10 ms/事件**，比任何 spawn 进程的 hook 都快，这是 DSH 侧最适合做高频事件的原因。

### E. 要真正"新动画/新画面"才需要动固件

现状：`Clawd-Mochi-Windows.zip` 里只有 3 个 4 MB 的成品 `.bin`，**没有 PlatformIO 工程源码**（文档里提到的 `common/mochi_firmware.cpp`、`common/sync_variants.py` 不在包里）。
所以：6 种表情的动画逻辑改不了；但"换画面"有两条免固件路：
1. `/image/upload` 给 7 个状态各换一张 240×180 图片（Wi-Fi 版；重烧完整镜像会清空）；
2. `/canvas` 模式实时画任意内容——本质上是"每帧自己画"，可以做出进度条、图表、像素动画（帧率受 HTTP 往返限制，本地 Wi-Fi 下约 30–50 ms/次）。

想改真正的动画状态机，只能向卖家要固件工程，或者自己按文档用 ESP32-C3 + Adafruit GFX/ST7789 重写。

> **这条已经做完了**：`<repo>\fw\` 是从零写的替代固件（`clawd-mochi-custom 0.1.4`），
> 内置动画从控制中心自带 GIF 里逐像素重建（251 帧误差 0），另加**任意多个自定义动画槽位**，
> 已烧进设备并实测通过；控制中心、设备网页、自定义图片上传都还兼容。
> 细节与烧录/回滚见 `fw\README.md`。

---

## 3. 本机实测记录

| 项目 | 结果 |
| --- | --- |
| 控制中心 | `D:\Program Files (x86)\Clawd-Mochi-Windows\Clawd-Mochi.exe`，v1.3.2，PID 32892，监听 18892/18893 |
| 连接方式 | Wi-Fi，`host=clawd-mochi.local`，`%APPDATA%\ClawdMochi\settings.json` |
| 设备 | `sta=true`、`ssid=MyHomeWiFi`、`speed=1`、`bl=true`、7 个状态都没有自定义图 |
| 已启用的 hook | claude_code、codex、qoder、workbuddy、gemini_antigravity、trae、deepseek_harness、doubao |
| 18892 白名单 | `idle` → 204；`planning`/`notify`/无参 → 400；`/` → 404 |
| 设备接口 | `/state` `/images` `/backlight` `/speed` `/cmd?k=w|s|d|q` `/char` `/redraw` `/canvas?on=1` `/draw/clear` `/draw/stroke` 全部 200，单次 30–100 ms（`/canvas?on=1` 约 2.8 s） |
| 扩展桥 demo | `thinking → coding(打字 "Bash: npm test") → 设备 view=2/term=true → progress 0.42 → view=3 画布 → waiting/error → done → 自动退出终端/画布`，全程 `errors=0` |
| hook 进程开销 | 控制中心的 PowerShell 方案 630–770 ms/次；`curl.exe` 33–55 ms；`mochi_hook.py` 230–380 ms；DSH 常驻插件 ~10 ms |

### 坑（都踩过）

1. **`/cmd?k=a` 不要碰**：实测会让设备连接重置（HTTP 连接被强制关闭），疑似触发启动动画/重启，之后才恢复。文档里没写这个键。
2. 终端视图会被随后的 `event` 打断（`term` 变回 `false`），所以扩展桥在打字前会重新 `GET /state` 确认再开终端。
3. 画布和终端互斥：桥在两者间切换时会先退出当前视图。
4. 控制中心"启用/移除 hook"会**重写**该工具的 hooks 配置（先备份 `.mochi-<时间>.bak`）。手动改过配置后，别在控制台再点这个开关，否则你的补充事件会被覆盖。
5. 重烧完整固件镜像会清空 LittleFS 里的自定义图片。
6. 18892 只认 GET 且只绑 127.0.0.1，所以外部机器/手机发不进来，必须是本机进程。
7. 若同时保留了控制中心的旧 hook 又挂新 hook，同一个状态会被发两遍（表情会抖）；选一套即可。

---

## 4. 目录

```
ext/
  mochi_bridge.py          扩展桥（127.0.0.1:18894）：13 事件 + 终端文字 + 画布进度 + 背景/速度/背光
  mochi_hook.py            单次 hook 客户端（任意平台可用，失败静默，exit 0）
  dsh-plugin/index.js      DSH 增强插件（替换控制中心自带插件）
  examples/claude-code-extra-hooks.json   给 Claude Code 补 Notification/PreCompact/Subagent* 的示例
  cs2/gamestate_integration_clawdmochi.cfg  CS2 的 GSI 配置（复制到 game\csgo\cfg\）
  cs2/start.bat / stop.bat   CS2 击杀动画桥的启动/停止脚本
  cs2_mochi.py             CS2 GSI 桥（127.0.0.1:18895）：击杀/连杀/爆头/死亡/回合 → 桌宠
  README.md                本文
_work/                     逆向与实测脚本（不属于交付物）
  device_probe.py          逐个打设备接口、打印 /state、最后恢复原状
  demo_bridge.py           端到端演示（按 hook 的方式调用，验证设备反应）
```

## 5. 回滚

- 停扩展桥：结束 `python mochi_bridge.py` 进程即可；设备状态不受影响。
- 恢复设备：`/cmd?k=q` → `/canvas?on=0` → `/redraw?bg=cd3400` → `/speed?v=1` → `/backlight?on=1` → `/cmd?k=w`。
- 回退 DSH 插件：把 `cordis.patch.yml` 里 `clawd-mochi-status` 的 `name` 指回 `%APPDATA%\ClawdMochi/deepseek_plugin/index.js`。
- 回退各工具 hooks：控制中心里关掉该工具的开关（会按 `.mochi-*.bak` 规则清理），或手动恢复备份。

## 6. CS2 击杀动画（Game State Integration）

原理：CS2 官方 GSI 把游戏状态 `POST` 到 `http://127.0.0.1:18895` → `cs2_mochi.py` 做差分识别 → 调设备 HTTP 播放动画。不进游戏、不改游戏文件、不碰 VAC（GSI 是 Valve 官方功能，和完美世界平台的 GSI 平级并存）。

### 安装（两步，缺一不可）
1. `ext\cs2\gamestate_integration_clawdmochi.cfg` 复制到
   `D:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg\`
   （已复制好，与 `gamestate_integration_cs2toolkit.cfg`、`gamestate_integration_pwa.cfg` 并存不冲突）
   → **必须重启 CS2 才生效**，GSI 配置只在游戏启动时读取。
2. 桥进程：`ext\cs2\start.bat`（用 pythonw 后台跑，无窗口），`stop.bat` 停止。
   查状态：打开 <http://127.0.0.1:18895/>（网页面板，带测试按钮）；
   程序读 JSON 用 <http://127.0.0.1:18895/status>；健康检查 <http://127.0.0.1:18895/health>。

### 自启动 / 开机就是好的
已在启动文件夹放了快捷方式，**登录 Windows 后自动起桥**：
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ClawdMochi-CS2.lnk`

当前快捷方式的参数（右键 → 属性 → “目标”里可改）：
```
"...\pythonw" "<repo>\ext\cs2_mochi.py" --slots --anim-map "1=done,2=coding,3=waiting,4=thinking,5=error"
```
（`--slots` = 用自写固件里的专属击杀动画槽；`--anim-map` 留作槽位缺失时的兜底）
改完记得 `stop.bat` 停掉旧进程再双击 `start.bat`（或注销重登）才会生效——正在跑的实例不会读新参数。

- 想改参数：右键该快捷方式 → 属性 → 在“目标”末尾加参数（比如 `--text --text-min-tier 2`）。
- 想关掉自启动：删掉这个 .lnk（不影响 `start.bat` 手动启动）。
- 桌面上还有两个 `.url` 快捷方式：`Clawd-Mochi CS2 状态.url`（18895 面板）、`Clawd-Mochi 控制台.url`（18893）。
- 桥挂掉的典型原因：被当成 DSH/终端的子进程连带杀掉。**这也是为什么现在只用“登录自启 + 桌面图标”来拉起它**，不要期望它跟着某个终端窗口活着。

### 击杀时发生什么（当前：自写固件专属动画）

**设备已经刷成自写固件**（`clawd-mochi-custom 0.1.4`，见 `<repo>\fw\README.md`），
里面预置了 8 个"真·专属动画"槽位，桥默认加 `--slots` 直接播它们，不再借用 6 个内置表情：

| 档位 | 颜色 | 播的槽位 | 停留 | 整段时长 |
| --- | --- | --- | --- | --- |
| 单杀 | `00FF66` | `kill1` 单杀 | 2400 ms | ≈3.4 s |
| 双杀 | `FFC400` | `kill2` 双杀 | 2800 ms | ≈3.8 s |
| 三杀 | `FF6A00` | `kill3` 三杀 | 3200 ms | ≈4.2 s |
| 四杀 | `FF2D00` | `kill4` 四杀 | 3600 ms | ≈4.6 s |
| ACE | `FF00FF` | `kill5` ACE | 4000 ms | ≈5.0 s |
| 死亡 | `FF2D00` | `death` 阵亡 | 1400 ms | ≈1.8 s |
| 回合胜/负 | — | `roundwin` / `roundlose`（需 `--round-fx`） | 1400 ms | ≈1.8 s |

桌宠下方状态牌会显示中文标签（单杀/双杀/三杀/四杀/ACE/阵亡/胜利/失败），播完自动回待机。

动画本体（宠物 + 彩色斜纹 + 中文大字 + 星芒）是 `fw\tools\gen_kill_anims.py` 画的、`pack_anim.py` 打的、
`upload_slot.py` 上传的；想换画面／加档位就再生成一套、换个槽位名，`--slot-map` 指过去即可，**不用重刷固件**。

> 旧模式（`--anim-map` + 6 个内置表情）仍然保留：去掉 `--slots` 就退回原厂那套"5 档复用 5 个表情"。

动作顺序（槽位模式）：直接 `/event?s=killN&h=<停留>` → 设备全屏播动画 → 到点自动回待机 → 桥补一个
`--rest-event idle` 复位。槽位模式下不再改底色/速度、也不打字幕（动画本身已经是整屏画面）。
连杀判定窗口 4.5 s；单杀文案按“怎么杀的”变：爆头 → `HEADSHOT`、刀杀 → `KNIFE KILL`、其余 `KILL`
（只在 `--text` 时用，槽位模式下显示的是动画里的中文大字）。

> 之前“彩色一闪而过、马上变回待机/已完成”是旧参数造成的：速度被设成 3（fast）+ 只停 1.15 s。
> 现在默认慢速 + 停 2.4 s 起。

### 常用参数（start.bat 后面可直接跟）
```bat
start.bat --slots                      :: 默认就是它：播自写固件里的专属击杀动画（kill1..kill5/death/roundwin/roundlose）
start.bat --slot-map "1=kill1,2=kill2,3=kill3,4=kill4,5=kill5"   :: 档位 → 槽位名（换了动画就改这里）
start.bat --death-slot death           :: 死亡播哪个槽位
start.bat --roundwin-slot roundwin --roundlose-slot roundlose   :: 回合胜负槽位（要配 --round-fx）
start.bat --anim error                 :: 【旧模式】所有击杀都换成“出错了”表情：done/error/thinking/coding/waiting/idle/sleep/none
start.bat --anim-map "1=done,2=done,3=coding,4=coding,5=error"   :: 【旧模式】按档位复用内置表情
start.bat --text --text-min-tier 2     :: 从双杀起在终端视图打字幕（槽位模式下建议别开，画面会被终端盖掉）
start.bat --canvas                     :: 同时在画布画准星/进度（槽位模式同理，会抢屏）
start.bat --round-fx                   :: 回合胜负也播
start.bat --no-bg --no-speed           :: 只播表情，不改底色/速度
start.bat --kill-hold 4000 --kill-hold-step 600   :: 单杀停 4 s、每高一档 +0.6 s（槽位模式的 h 就是这个）
start.bat --fx-speed 2                 :: 动画速度 1慢/2正常/3快（默认 1；槽位动画不受影响）
start.bat --bg-lead 900                :: 彩色底色多亮 0.9 s 再播（0=不闪；槽位模式不走这条）
start.bat --hold 1400                  :: 死亡/回合这类非击杀动作的停留毫秒
start.bat --dry-run                    :: 只解析不驱动设备（调参用）
python cs2_mochi.py --self-test        :: 离线自测识别逻辑
```

### 不玩游戏也能试
```powershell
Invoke-RestMethod 'http://127.0.0.1:18895/replay?kind=kill&tier=5'   # ACE
Invoke-RestMethod 'http://127.0.0.1:18895/replay?kind=kill&tier=2'   # 双杀
Invoke-RestMethod 'http://127.0.0.1:18895/replay?kind=death'
Invoke-RestMethod 'http://127.0.0.1:18895/replay?kind=round&win=1'
```

### 坑
1. GSI 配置**只在游戏启动时读**，改完/新装必须重启 CS2。
2. 连杀时旧动画会排队堆积 → 默认只留 2 个任务，最新的优先。
3. 退出终端视图必须 `cmd("w")`；只发 `/cmd?k=q` 会停在 Claude Code 视图（只关了终端）。
4. 只在 `activity` 为 `playing`/`textinput` 时判断，菜单里不会误触发。
5. 若同时留着控制中心自带的 hook，同一个"工作中"表情可能被别的 agent 事件覆盖——想完全由 CS2 独占就把 `--no-stock` 用在 `mochi_bridge.py` 上，或干脆只用 cs2_mochi.py。
6. `--text`（终端打字）一次约 4 s：每个字符都要一次 HTTP。所以默认关着，建议配 `--text-min-tier 2` 只在多杀时出现。
7. `start.bat` 请双击（或从 Explorer 运行）；从别的程序里用管道调用它，调用方可能等不到结束（pythonw 是常驻进程）。

### 回滚
- 停桥：`ext\cs2\stop.bat`。
- 彻底移除：删掉 `game\csgo\cfg\gamestate_integration_clawdmochi.cfg`（重启 CS2 后 CS2 就不再发 GSI 给本机 18895）。
- 把桌宠固件退回原厂（专属击杀动画会失效，改用内置表情）：
  ```
  python -m esptool --chip esp32c3 --port COM11 --baud 460800 write_flash 0x10000 `
    <repo>\_work\app_ota0.bin
  ```
  然后桥去掉 `--slots`（或改回 `--anim-map`）。完整说明见 `fw\README.md` 第 5 节。
- 槽位素材太多占空间：`fw\tools\upload_slot.py --delete kill5` 之类逐个删；或直接整片刷回原厂镜像清空 LittleFS。
### 槽位播放优先级（固件 0.1.2 起）

设备在播自定义槽位（kill1..5 / death / roundwin / roundlose）期间，会**忽略原厂 13 种状态事件**，
所以 agent 的 hook（18892 推来的 coding/idle 等）不会把击杀动画在一秒内顶掉。播完按 h= 到点自己回 idle。

### 桥没反应时先重启它

cs2_mochi.py 是常驻进程（启动文件夹快捷方式拉起）。如果 /replay 后设备没反应、/status 里
device_connected 是 alse，先重启桥（实测遇到过一次：进程在设备离线期间启动，之后一直没恢复）：

    taskkill /f /im pythonw
    powershell -Command "([wmiclass]'Win32_Process').Create('\"pythonw\" \"<repo>\ext\cs2_mochi.py\" --slots --anim-map \"1=done,2=coding,3=waiting,4=thinking,5=error\"')"

重启后 /status 应显示 device_connected: true、x.slots 有 5 个档位。
