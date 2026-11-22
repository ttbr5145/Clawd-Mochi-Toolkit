# Clawd-Mochi 自写固件（clawd-mochi-custom 0.1.4）

原厂 Wi-Fi 固件只能"13 种事件 → 6 组内置画面 + 7 个静态图片槽位"。这个固件把"画面"变成
**任意多个自定义槽位**：可以上传任意多个动画（帧序列）和静态图，用 `/event?s=<槽位名>` 就能播，
并且完全兼容原厂控制中心（Windows 端 Clawd-Mochi.exe v1.3.2）和原厂设备网页。

- 设备网页：`http://clawd-mochi.local/`（原厂控制器，未改）
- WiFi 配网：`http://clawd-mochi.local/wifi`
- 控制中心连它：`http://127.0.0.1:18893/`（照常轮询/发事件，实测已通）

## 0. 版本历史

| 版本 | 内容 |
| --- | --- |
| `0.1.4` | **官方 USB/串口控制协议**（`PING`/`EVENT <名>`/`STATE`/`VIEW idle|sleep`/`BACKLIGHT`/`SPEED`/`BG`，控制中心"USB 有线"模式可用）；**串口命令行**（`ip`/`scan`/`state`/`net <url>`/`wifi <ssid> [pass]`/`save`/`forget`/`reboot`）；**多网络自动尝试**（`DEFAULT_NETS`: MyHomeWiFi / NEFU-WIFI / NEFU-EDUROAM）；**网络诊断端点** `/net/get?url=&follow=`、`/wifi/status`、`/wifi/try`。连网阻塞期间用 `net::setPollHook()` 让串口仍能应答 `PING`。镜像 ~1.2 MB（引入 HTTPClient/mbedTLS）。 |
| `0.1.2` | 在 0.1.1 基础上加**槽位播放优先级**：`showEvent()` 里当 `state==ST_SLOT && (int32_t)(slotUntil-millis())>0` 时忽略原厂 13 种状态事件（idle/coding/…/fail），击杀/死亡/回合动画不会被 agent 的 hook 事件在一秒内覆盖。实测：槽位播放期间连推 coding/idle/busy，动画仍播完再回 idle。 |
| `0.1.1-sleepfix` | **修内置「休息中」动画**：控制中心预览 GIF 的第 1..35 帧是"局部帧"，旧提取脚本把 tile 之外填成 GIF 逻辑背景色（奶白 #FFF6E7），导致「休息中」显示成奶白/黑白底。改用 `fw/tools/gif_compose.py` 叠加合成后重新提取，全部 7 个动画逐帧重绘校验 meanDiff=0.000；实测「休息中」恢复"黑底 + 橙宠物 + 上升 Zzz"。 |
| `0.1.0-inv` | 首个可用版本：任意多自定义槽位（CMA1 动画 / RGB565 静态图）、扩展 HTTP API、面板反显修正（默认 `inv=1`，否则橙色变浅蓝）。 |

## 1. 和原厂固件的差别

| 能力 | 原厂 | 本固件 |
| --- | --- | --- |
| 13 种 AI 事件 → 内置画面 | ✅ | ✅（画面用原厂 GIF 逐像素重建，251 帧 meanDiff=0） |
| 7 个静态图片槽位（240×180） | ✅ | ✅（`/image/upload` 协议不变，控制中心可直接上传） |
| 自定义动画槽位 | ❌（只能换 7 个槽的静态图） | ✅ **任意多个**，LittleFS 里按名字存 |
| 播自定义动画 | ❌ | ✅ `/event?s=kill1&h=3200` |
| 终端视图 / 画布 / 底色 / 速度 / 背光 | ✅ | ✅ |
| 截图 | ❌ | ✅ `/screenshot.bmp`（240×240 24bit BMP） |
| 远程调屏幕朝向 | ❌ | ✅ `/panel?rot=&inv=`（存 NVS，重启不丢） |
| 状态牌文字 | 内置位图 | 内置位图 + 8 个击杀场景的中文标签位图（单杀/双杀/三杀/四杀/ACE/阵亡/胜利/失败） |

内置动画的每一帧都被拆成"纯色矩形表"存进 `src/assets.h`（30,893 个矩形，251 帧，约 155 KB），
所以表情和原厂一模一样，不占 LittleFS。

## 2. 硬件（最新硬件，8 线）

| 屏幕 | ESP32-C3 |
| --- | --- |
| VCC | 3V3（只接 3.3V） |
| GND | GND |
| SDA / MOSI | GPIO3 |
| SCL / SCK | GPIO4 |
| DC | GPIO5 |
| RST | GPIO6 |
| BL | GPIO7 |
| CS | GPIO8 |

屏是 1.54" ST7789 **240×240**，固件里 `setRotation(2)`（官方文档写明最新硬件 `TFT_ROTATION = 2`）。
舞台（表情/自定义画面）= 上方 240×180，状态牌 = 下方 60px，由固件直接画到面板。

早期 SuperMini 套件引脚不同（MOSI 10 / SCK 8 / RST 2 / DC 1 / CS 4 / BL 3），**不要混用**。

## 3. 编译

```powershell
cd <repo>\fw
pio run
```

当前结果：`Flash 38.8% (1,221,286 / 3,145,728)`、静态 `RAM 13.0%`，产物
`fw\.pio\build\clawdmochi\firmware.bin`（约 1.2 MB）。

首次编译会下载 espressif32 平台（约 15 分钟），之后 ~35 秒。

## 4. 烧录

> **本仓库不附带任何 .bin 镜像**：原厂固件是第三方代码，自编译镜像又内嵌了从原厂素材
> 提取的画面，两者都不能再分发。所以请自己 `pio run` 出镜像、并自己备份原厂固件（见 §5）。

**推荐：先编译，再双击 `fw\dist\FLASH-custom.bat`（或 `FLASH-custom.bat COM11`）**

```powershell
cd <repo>\fw
pio run
copy .pio\build\clawdmochi\firmware.bin  <repo>\fw\dist\clawdmochi-custom.bin
```

`FLASH-custom.bat` 只写 app 区（0x10000），等价命令：

```powershell
python -m esptool --chip esp32c3 --port COM11 --baud 460800 --after hard-reset write-flash 0x10000 `
  <repo>\fw\dist\clawdmochi-custom.bin
```

想保留历史版本就多复制几份带版本号的名字（如 `clawdmochi-custom-0.1.4.bin`），
并改 `FLASH-custom.bat` 里的 `set IMG=`。

已核对：自编译 `partitions.bin` 与设备里现有分区表**逐字节相同**（nvs 0x9000/0x5000、
otadata 0xe000/0x2000、app0 0x10000/0x300000、spiffs 0x310000/0xE0000、coredump 0x3F0000/0x10000），
所以只写 0x10000 是安全的。串口是**原生 USB CDC**，设备用 USB 连电脑即出现 `COM11`
（VID 303A PID 1001）。烧录时不用按 BOOT。

> **如果提示 `Could not open COM11`**：极少情况下 esptool 复位后 Windows 会把这个串口挂成"未知设备"
> （实测遇到过一次）。解决：拔插一次 Type-C 线，或按住 BOOT 点一下 RST 再松开（进下载模式），然后重跑脚本。

**整片刷（会清 WiFi 配置和所有自定义素材）**

```powershell
python -m esptool --chip esp32c3 --port COM11 --baud 460800 --after hard-reset write-flash 0x0 <4MB 完整镜像>
```

## 5. 回滚到原厂

**先备份**（在刷自编译固件之前就该做，否则原厂镜像就没了）：

```powershell
# 整片 4MB 备份，写进 fw\dist\factory-full-backup.bin
python -m esptool --chip esp32c3 --port COM11 --baud 460800 read-flash 0x0 0x400000 `
  <repo>\fw\dist\factory-full-backup.bin

# 从整片备份里切出原厂 app 区（0x10000..0x310000）作为 clawdmochi-stock-app.bin
# 例：python 一行，读 factory-full-backup.bin 的 0x10000 起 0x300000 字节写出
```

`fw\dist\` 里有两个一键脚本（原厂镜像需要你自己放进去）：

```powershell
# 1) 只回滚 app（推荐，保留 NVS 里的 WiFi 凭据和 LittleFS 里的自定义素材）
fw\dist\RESTORE-factory-app.bat COM11      # 需要 clawdmochi-stock-app.bin

# 2) 整片恢复出厂（会清空 WiFi 配置与自定义素材）
fw\dist\RESTORE-factory-full.bat COM11     # 需要 factory-full-backup.bin，有二次确认
```

等价命令：

```powershell
python -m esptool --chip esp32c3 --port COM11 --baud 460800 --after hard-reset write-flash 0x10000 `
  <repo>\fw\dist\clawdmochi-stock-app.bin
python -m esptool --chip esp32c3 --port COM11 --baud 460800 --after hard-reset write-flash 0x0 `
  <repo>\fw\dist\factory-full-backup.bin
```

原厂固件和本固件用不同的 NVS 命名空间（原厂用默认、本固件用 `mochi`），互不干扰；
回滚 app 后 LittleFS 里的自定义槽位还在，只是原厂不认它们（`/slot/list` 等扩展端点也随之消失）。

## 6. 设备 HTTP API

### 6.1 原厂接口（全部实现，行为对齐）

| 接口 | 说明 |
| --- | --- |
| `GET /` | 原厂设备控制器网页（原样内嵌） |
| `GET /wifi` | 原厂 WiFi 配网页 |
| `GET /state` | `{"ok":1,"view":0,"busy":false,"term":false,"bl":true,"speed":1,"sta":true,"ssid","ip","rssi","fw","name","anim","slots","bg","heap","uptime"}`；`view`: 0=普通眼 1=眯眼 2=终端 3=画布 |
| `GET /event?s=<事件>[&h=毫秒]` | 13 个原厂事件名 + **任意槽位名**；`h` 是自定义停留毫秒 |
| `GET /cmd?k=w\|s\|d\|q\|a` | w→普通眼，s→眯眼，d→终端，q→关终端回普通眼，a→出个"出错"表情（原厂 logo 彩蛋位） |
| `GET /char?c=<一个字符>` | 终端打字（`%08` 退格、`%0A` 回车） |
| `GET /speed?v=1\|2\|3` | 动画速度 1=1.0× 2=1.43× 3=2.5× |
| `GET /backlight?on=0\|1` | 背光 |
| `GET /redraw?bg=RRGGBB` | 改底色并回普通眼视图 |
| `GET /canvas?on=0\|1` | 进入/离开画布 |
| `GET /draw/clear?bg=RRGGBB` | 清画布 |
| `GET /draw/stroke?pen=RRGGBB&pts=x,y;x,y…` | 画折线 |
| `GET /images` | `{"ok":1,"custom":{"0":false,…,"6":true},"slots":[{"name","type","size"}]}`（控制中心的图片页读这个） |
| `POST /image/upload?state=N` | multipart，字段名 `image`，文件 240×180 RGB565 = **86,400 B**（低字节在前）；控制中心即用此协议 |
| `GET /image/reset?state=N` | 恢复该状态的默认动画 |
| `GET /wifi/scan` `/wifi/save?ssid=&pass=` `/wifi/forget` | 扫描 / 保存后重启 / 清凭据后重启 |

### 6.2 新增接口

| 接口 | 说明 |
| --- | --- |
| `GET /health` | `{"ok":1}` 轻量探活 |
| `GET /anim/list` | 内置动画名列表 |
| `GET /slot/list` | 槽位列表（名字/类型/大小） |
| `POST /slot/upload?name=<槽位名>` | multipart，字段名 `file`；`.cma`=动画，`.rgb`=静态图 |
| `GET /slot/delete?name=<槽位名>` | 删除槽位 |
| `GET /screenshot.bmp` | 当前整屏 240×240 24bit BMP（含状态牌），直接浏览器打开即可看 |
| `GET /panel?rot=0..3&inv=0\|1` | 远程调屏幕旋转/反色，写入 NVS |

## 7. 素材格式

### 7.1 静态图槽位 `.rgb`

`240×180` 的 RGB565 原始像素，**86,400 字节**，每个像素 2 字节低字节在前：
`v = ((r>>3)<<11) | ((g>>2)<<5) | (b>>3)`。

### 7.2 动画槽位 `.cma`（CMA1，小端）

```
0    'C','M','A','1'
4    u16 version = 1
6    u16 pal_n      (<=256，pal[0] 是底色)
8    u16 frame_n    (<=512)
10   u16 bg_idx     (调色板里当底色的下标，通常 0)
12   u16 reserved / u16 reserved
16   palette  u16[pal_n]      RGB565
..   frames   {u16 dur_ms, u16 rect_n} × frame_n
..   rects    5 字节/条：u8 pal_idx, u8 x, u8 y, u8 w, u8 h（按帧顺序，pal_idx==0 的块跳过）
```

固件播放时按帧 `seek` 到对应矩形段、分块读（64 条=320 B 一块），所以文件多大都不会把堆吃满。
矩形顺序无所谓（后画的盖先画的），生成器已按 `(y,x)` 排序。

## 8. 工具（`fw/tools`）

| 脚本 | 用途 |
| --- | --- |
| `extract_assets.py` | 从控制中心自带 GIF 提取内置动画矩形表 + 状态牌位图 → `src/assets.h`（已生成，一般不用再跑） |
| `gif_compose.py` | GIF 局部帧合成器：`load_frames()` 把 tile 叠到上一帧上。**必须用它读帧**，直接用 `ImageSequence` 会把 07_sleep 的帧外区域填成奶白 |
| `embed_pages.py` | 把原厂设备网页转成 `src/web_pages.h`（已生成） |
| `patch_assets.py` / `patch_stage.py` / `patch_slotlabel.py` | 生成器的一次性补丁脚本（保留备查） |
| `gen_slot_labels.py` | 生成 8 个击杀场景的中文状态牌位图 → `src/slot_labels.h` |
| `gen_kill_anims.py` | 生成击杀/阵亡/回合胜负 GIF（像素风宠物 + 中文标签）→ `_work/kill_anim/` |
| `pack_anim.py` | GIF/PNG → `.cma`（动画）或 `.rgb`（静态图） |
| `upload_slot.py` | 上传/列出/删除槽位、抓截图 |
| `test_image_upload.py` | 验证控制中心那条 `/image/upload` multipart 协议 |
| `cmp_part.py` | 比对自编译分区表与设备备份里的分区表 |

常用命令：

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
cd <repo>\fw\tools

# 生成 + 打包 + 上传一套击杀动画（已做过，设备上已有 kill1..kill5/death/roundwin/roundlose）
& $py gen_kill_anims.py
& $py pack_anim.py ..\..\_work\kill_anim\kill1.gif --name kill1
& $py upload_slot.py ..\..\_work\anim_pack\kill1.cma --name kill1

& $py upload_slot.py --list
& $py upload_slot.py --shot ..\..\_work\shot.bmp
```

## 9. 实测记录

2026-11-16 首次上机（固件 0.1.0），2026-11-17 补 0.1.1 休眠动画修复验证。

| 项目 | 结果 |
| --- | --- |
| 只写 app（0x10000）后开机 | ✅ 自动连上 `MyHomeWiFi`，IP `192.168.1.11`，mDNS `clawd-mochi.local` 可用 |
| `/state` | ✅ `fw:0.1.0`、`sta:true`、`rssi:-7x`、`heap:~123 KB`、`slots:8` |
| `/`（原厂控制器页） | ✅ 200 `text/html` 17,442 B（与原厂一字不差） |
| `/wifi`（配网页） | ✅ 200 `text/html` 5,989 B |
| 原厂控制中心 v1.3.2 | ✅ `/api/status` 里 `device.connected=true`；它发的 `coding` 事件能让设备进"工作中"（旧链路照常） |
| 内置动画渲染 | ✅ 与原厂 GIF 逐像素一致（提取时 251 帧 meanDiff=0）；截图见 `/screenshot.bmp` |
| `/event?s=kill1..kill5&h=` | ✅ 槽位动画整屏播放，状态牌显示中文（单杀/双杀/三杀/四杀/ACE） |
| `/image/upload`（控制中心 multipart 协议） | ✅ 86,400 B RGB565 上传成功、`/images` 的 `custom[2]=true`、切到工作中显示新底图；`/image/reset?state=2` 恢复默认动画 |
| `/slot/upload`（multipart `file`） | ✅ 8 个动画槽位全部上传成功（29~86 KB/个） |
| 重启后持久化 | ✅ esptool 硬复位后 `slots:8` 仍在、WiFi 自动重连、开机回 `idle` |
| `/screenshot.bmp` | ✅ 172,854 B 合法 24bit BMP（PIL 可读） |
| 桥端到端 | ✅ `cs2_mochi.py --slots`：`/replay` 三杀/四杀/ACE/死亡 → 设备 `anim:slot`，到点自动回 `idle`，`errors=0` |

## 10. 已知限制 / 待验证


1. **面板颜色/朝向**：面板默认 `inv=true`（反显）——原厂面板就是反显的，不反显会出现橙色→浅蓝、黑边→白边（"幽灵"）效果；`rot=2` 已由用户实测确认朝向正确。
   若开机发现"状态牌跑到上面"，需要改时用 `/panel?inv=0|1` 或 `/panel?rot=0..3`（立即重画并写入 NVS；旧 `cfgv<2` 的残留值开机时会被强制重置为反显）。
2. 只做了 Wi-Fi 版；USB/BLE 版协议相同但这次没烧。
3. 播放动画期间 `/state` 的 `busy` 一直是 `false`（没有实现"忙"语义），原厂控制器页的忙轮询不会阻塞，反而更好用。
4. 控制中心里若出现本固件没实现的接口（例如设备配置写入），那个按钮会静默失败；不影响事件/图片/控制这三条主链路（都实测通过）。
5. LittleFS 分区 896 KB，目前 8 个击杀动画占 ~453 KB；再往里塞大型动画要注意剩余空间（`/state` 里没有暴露 FS 余量，`/images` 的 slots 有各自大小）。

## 11. 素材清单（设备上现有的）

| 槽位 | 类型 | 大小 | 用途 |
| --- | --- | --- | --- |
| kill1 / kill2 / kill3 / kill4 / kill5 | anim | 66,682 / 85,647 / 61,182 / 68,057 / 76,402 B | 单杀/双杀/三杀/四杀/ACE |
| death | anim | 29,536 B | 阵亡 |
| roundwin / roundlose | anim | 32,871 / 31,778 B | 回合胜/负 |

全部 12~8 帧、100~120 ms/帧，状态牌标签自动显示中文。
