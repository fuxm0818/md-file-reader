# 贡献指南

先说清楚这个项目的定位：一个自用的 macOS 离线朗读工具，优先解决「边看边听」这个流程上的问题。如果你想加的功能偏离这个方向（比如在线语音、云同步、账号体系），大概率不会合。

## 提问题

开 [Issue](https://github.com/fuxm0818/md-file-reader/issues) 前先搜一下有没有重复。说清楚：

- 系统版本（`sw_vers -productVersion`）和是否装了中文语音
- 文档是什么格式、多大、能不能用 `samples/` 里的样本复现
- 你期望发生什么，实际发生了什么

能附上 `DOCREADER_SELFTEST=1` 的输出最好：

```bash
DOCREADER_SELFTEST=1 /Applications/文档朗读器.app/Contents/MacOS/文档朗读器
```

语音相关的问题多半能从这段 JSON 里看出是音色缺失、合成失败还是后处理没生效。

## 提代码

1. Fork 后从 `main` 开一个分支，名字说明改什么：`fix/splitter-not-saved`
2. 提交信息用 `类型(范围): 说明`，类型取 `feat` / `fix` / `chore` / `docs` / `test`，例如 `fix(controller): 退出时等待合成任务`
3. 改完跑测试，全绿再提 PR

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/run_qa.py
```

4. PR 里说明为什么这么改，而不是只贴 diff

## 代码约定

**用例先行。** 修 bug 先想清楚怎么用一条用例把它钉住，再改代码。用例规格写在 `tests/docs/0*-TEST-CASES.md`，实现写在 `tests/e2e/`，两边要对应；新用例还要在 `tests/e2e/conftest.py` 的 `CASE_CATALOG` 里登记。

**注释写「为什么」。** 这段代码在绕开什么问题、试过什么行不通，比它做了什么更有价值。纯描述性的注释不如删掉。

**不要碰真实的用户数据。** 测试和脚本一律把状态目录指到 `.qa-workspace/`，绝不能读写 `~/Library/Application Support/文档朗读器/`。`scripts/make_screenshot.py` 是最直接的例子。

**界面改动不要看感觉。** 配色、字号、间距都在 `src/ui/theme.py` 里，加新控件用那里的令牌，不要直接写颜色值。图标用 `theme` 的矢量绘制，不引入图片素材。

**语音相关改动要实测。** 改后处理参数后，拿一段真实文本量一下峰值和电平（见 `tests/e2e/test_voice.py::test_system_voice_output_is_polished`），别只凭听感。

## 发版

维护者操作：全量用例通过 → 更新 `CHANGELOG.md` → 打 tag 推送。

```bash
git tag -a v1.4.0 -m "v1.4.0"
git push origin v1.4.0
```

`v*` 标签会触发 `.github/workflows/build-macos.yml`：重跑测试门禁、打包、跑冻结进程自检、上传 Release 资产。

## 许可

提交的代码按 [MIT](LICENSE) 授权。
