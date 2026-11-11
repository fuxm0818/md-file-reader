# 语音自然度优化测试用例 · v1.1.0

> 本文件是**唯一真实来源**：用例规格、步骤与预期结果以此为准；
> `templates/TEST-EXECUTION-TRACKING.csv` 只记录执行状态，由 pytest hook 自动回写。
> 对应实现：`src/core/oralizer.py`、`src/core/prosody.py`、`src/core/speech.py`、
> `src/controller.py`、`src/ui/settings_dialog.py`。

## 背景与验收目标

用户反馈「声音太硬、没有断句、没有语气」。本轮在不换引擎、不联网、不加第三方依赖的前提下，分三层优化：

| 层 | 能力 | 明确边界 |
|---|---|---|
| L0 音色 | 默认改用 Apple 现代中文音色；空音频自动降级 | 仍无法产生情绪与角色 |
| L1 口播稿 | 长句拆短、书面词换口语词、数字符号口语化 | **只改写送给合成器的副本**，正文显示与高亮坐标不变 |
| L2 韵律 | `[[slnc]]` 气口、`[[rate]]` 局部语速、`[[pbas]]` 句类音高 | `[[pmod]]`/`[[emph]]` 对中文音色无效，重音靠停顿与语速对比 |

实测依据（本机 macOS / `say` + `afinfo` + 波形自相关）：
- 184 个音色、19 个中文，其中 8 个现代音色；`Tingting` 为最老音色。
- `[[slnc 1200]]`：4.08s → 5.14s；`[[rate 160]]`：4.87s → 5.47s；`[[pbas +25]]`：F0 108 → 210 Hz；`[[volm 0.7]]`：RMS 4591 → 2004。
- 短名 `Sandy` 会静默产出 0.016s 空音频（rc=0、无 stderr），完整标识 `Sandy (中文（中国大陆）)` 才正常 → 必须做时长体检。
- 样例改稿：91 字 → 80 字；Tingting 19.79s → 21.47s（+8.5%，多出的是气口）。

---

## TC-NAT-001 · P0 · 口播化改写：拆句 / 换词 / 符号

**前置**：`src.core.oralizer` 可导入。
**步骤**
1. 输入 `文档本身没有时间轴，所以程序按语速把字数换算成时间。已经合成过的句子会用音频的真实时长替换估算值，剩余时间会越听越准。`
2. 调用 `oralize()`；记录输出与汉字数。
3. 另输入 `支持 ±15s 与 80% 的进度，此外 A&B 以及 [链接](https://x) 也可以。` 再调用。

**预期**
- 「换算成」被替换为「换成」；超长逗号片段至少有一处升级为句号（长句被拆短）。
- 汉字数不增加（去除冗余，不新增内容），输出非空。
- `±15s` → `正负15秒`；`80%` → `百分之80`；`此外` → `另外`；`&` → `和`；`以及` → `还有`；Markdown 链接只保留锚文本，URL 不被朗读。

## TC-NAT-002 · P1 · 因果句改为先结论后原因且语义等价

**前置**：同上。
**步骤**：输入 `因为文档没有时间轴，所以程序必须自己换算时间。`，调用 `oralize()`。
**预期**：输出以「程序必须自己换算时间」开头，含「这是因为文档没有时间轴」；原句中「因为」「所以」不再以原顺序出现；两个事实片段均完整保留，不丢信息。

## TC-NAT-003 · P0 · 改写不破坏正文坐标与高亮映射

**前置**：`samples/示例文档.md` 可解析。
**步骤**
1. `parse()` 得到 `doc`，记录 `display_text` 长度、每句 `(start, end)`。
2. 对每句调用 `oralize()` 与 `render()`。
3. 再次检查 `doc.display_text` 与所有 span。

**预期**：`display_text` 逐字不变；所有 span 仍满足 `0 <= start < end <= len(display_text)`；改写结果与原句长度/内容可以不同，但 `doc` 对象本身零变化。

## TC-NAT-004 · P1 · 技术类文档自动关闭改写

**前置**：`oralize_enabled()`。
**步骤**：分别以 `a.md`、`a.txt`、`a.pdf`、`a.docx` 与 `a.py`、`a.json`、`a.csv`、`a.log` 调用（主开关 True）；再以 `a.md` + 主开关 False 调用。
**预期**：文档类扩展名返回 True；代码/数据类扩展名返回 False；主开关关闭时一律 False。

## TC-NAT-005 · P0 · 韵律渲染插入气口，四档强度单调递增

**前置**：`src.core.prosody.config / render / estimated_pause`。
**步骤**：对同一段含逗号与句号的文本，分别以 level 0/1/2/3 渲染（rate=200，`is_para_end=True`）；统计 `[[slnc ...]]` 条数与总停顿秒数。
**预期**：level 0 不含任何 `[[...]]` 命令且文本原样返回；level 1→2→3 的停顿秒数严格递增；level 3 额外含 `[[pbas ...]]`；越界 level（-1、99）被钳制到 0/3 不抛异常。

## TC-NAT-006 · P0 · 文档正文不得注入 say 嵌入命令

**前置**：`sanitize()` 与 `render()`。
**步骤**：构造含 `[[slnc 999999]]`、`[[rate 400]]`、`[[pbas +99]]` 的恶意句子，分别以 level 0/2 走 `render()`；并用 `ReaderController._speech_text()` 生成合成文本。
**预期**：所有来自正文的 `[[...]]` 被剥离；渲染结果中的 `[[slnc]]` 只可能是程序按标点插入的合法值（≤850ms）；`[[rate]]` 只能出现在句首且为钳制后的速率；无 `[[pbas +99]]` 等用户可控值。

## TC-NAT-007 · P1 · 停顿预算与实测停顿一致，时间轴估算含补偿

**前置**：`pause_budget()`、`Timeline`。
**步骤**：计算 level 0/1/2/3 的 `pause_budget`；用同一段文本渲染 level 2 求 `estimated_pause`；构造 3 句文档，分别用 `Timeline(doc, 0.2)` 与 `Timeline(doc, 0.2, PAUSE + pause_budget(2))` 求总时长。
**预期**：预算随档位单调递增且 level 0 为 0；level 2 预算与典型句实测停顿偏差 ≤0.4s；带补偿的时间轴总时长严格大于默认时间轴，`set_real()` 校准仍生效。

## TC-NAT-008 · P1 · 默认音色优先现代音色，旧列表回退兼容

**前置**：`list_voices()`、`choose_voice()`、`Voice.is_modern`。
**步骤**：用本机真实音色列表调用 `choose_voice()`；再传入只含 `Alex/Sinji/Tingting/Meijia` 的假列表；再传 `preferred="Meijia"`。
**预期**：真实列表返回的音色 `is_modern=True` 且 locale 为 `zh_CN`；假列表仍返回 `Tingting`（旧行为不回归）；用户显式偏好优先；只有非中文音色时返回 None；仅 `zh_HK` 时返回 `Sinji`。

## TC-NAT-009 · P1 · 空音频判定与自动降级

**前置**：`SpeechEngine`、`MIN_AUDIO_DURATION`。
**步骤**
1. 桩使 `probe_duration` 返回 0.01（模拟未下载音色的空音频），调用 `synthesize()`。
2. 用 `make_controller` 构造控制器，桩使第一次 `synthesize` 返回 `EMPTY_AUDIO:Bad`、之后返回正常音频，调用 `_ensure_usable_voice()`。

**预期**：第一步返回 `(None, 0.0, "EMPTY_AUDIO:<音色>")` 且不留 `.aiff` 缓存；第二步返回 True、音色已切换、`settings["voice"]` 同步更新、`startup_message` 非空。

## TC-NAT-010 · P1 · 缓存键随改写开关 / 节奏强度 / 音色 / 语速隔离

**前置**：`SpeechEngine.key()`。
**步骤**：对同一原句分别生成「原样 level 0」「改写 level 2」「改写 level 3」三种合成文本；再对同一文本换音色、换语速。
**预期**：五种组合的 key 两两不同；相同输入重复调用 key 稳定；key 长度固定且仅含十六进制字符（不可被用作路径遍历）。

## TC-NAT-011 · P1 · 自然度设置生效并持久化

**前置**：`make_controller` + 隔离 `state.json`。
**步骤**：调用 `set_oralize(False)`、`set_prosody_level(3)`；读取 state.json；重新 `Store().load()`；再调用 `set_prosody_level(99)` 验证钳制。
**预期**：设置写入并可从磁盘读回；`settingsChanged` 触发、时间轴按新档位重建；越界值被钳制到 3；当前句仍能正常加载（不 because 设置变更而卡死）。

## TC-NAT-012 · P1 · 试听不打断当前播放

**前置**：控制器已加载样例文档并开始播放。
**步骤**：记录 `c.player.playbackState()` 与 `c.sentence_index`；调用 `preview_voice()`；再次检查。
**预期**：`c._preview_player` 被赋值且非 None；主播放器状态与句子索引保持不变；状态栏收到包含音色名与节奏档位的消息。

---

## 覆盖与口径

- 本组 12 条：P0 4 条、P1 8 条。全库合计 **64 条**（原 52 + 本组 12）。
- 覆盖率范围不变：`src/core/*.py` + `src/controller.py`；新增的 `oralizer.py`、`prosody.py` **计入分母**，不放水。
- OWASP 口径不变：TC-NAT-006 属于新增注入面的防护用例，作为 A03 注入类目的补充证据，不改动 `03-SEC-TEST-CASES.md` 的 10 类结论表。
