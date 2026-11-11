# 04 · 打包与发布流水线测试用例（权威来源）

**项目**：文档朗读器 v1.0.0　**分类**：PKG / CI
**目标**：确保 `tag v*` 推送后 GitHub Actions 能自动完成「质量门禁 → 打包 → 自检 → Artifact → Release」。

---

### TC-PKG-001: build.sh 构建契约
**优先级**: P0　**类型**: 静态契约　**预估**: 1 min
**前置条件**: 仓库根目录可读。
**测试步骤**: 1. 读取 `build.sh`；2. 校验关键参数；3. 校验文件可执行位。
**预期结果**: ✅ 指定 `--onedir --windowed --name 文档朗读器`；✅ `--paths` 指向仓库根（保证 `src` 包导入）；✅ 含 `PySide6.QtMultimedia` / `pymupdf` / `docx` 三个 hidden-import；✅ 含 ad-hoc `codesign`；✅ 旧产物用 `mv` 移走而非批量删除；✅ 脚本具备可执行权限。
**通过/失败**: 任一契约缺失为失败（会导致打包后 GUI 启动即崩）。
**潜在缺陷**: PyInstaller `--clean` 触发批量删除保护；缺少 hidden-import 导致冻结后 ImportError。

### TC-PKG-002: 依赖清单完整且可分环境复现
**优先级**: P0　**类型**: 静态契约　**预估**: 1 min
**前置条件**: `requirements.txt` / `requirements-dev.txt` 存在。
**测试步骤**: 1. 解析两份清单；2. 检查运行时依赖四项（PySide6 / pymupdf / python-docx / pyinstaller）与测试依赖（pytest / pytest-cov）；3. 检查每一项版本约束。
**预期结果**: ✅ 运行时与开发依赖分离；✅ 关键包齐全且有版本约束；✅ `pymupdf<2`；✅ 当前虚拟环境可导入 PySide6 / pymupdf / docx / pytest。
**通过/失败**: 缺包或无版本约束为失败。
**潜在缺陷**: CI 装到 PyMuPDF 2.x 附带 ONNX 模型，产物膨胀数百 MB。

### TC-PKG-003: 打包产物存在、已签名且自检通过
**优先级**: P1　**类型**: 实机 / 契约降级　**预估**: 3 min
**前置条件**: 本地若存在 `dist/文档朗读器.app` 则执行实机自检；CI 打包前则该产物由 workflow 独立 step 验证。
**测试步骤**: 1. 检查 `.app/Contents/MacOS/文档朗读器` 是否为可执行文件；2. 检查 `codesign -dv` 签名信息；3. 若存在则带 `DOCREADER_SELFTEST=1` 运行并解析 `/tmp/docreader_selftest.json`；4. 产物不存在时，验证 workflow 中含等价的自检 step。
**预期结果**: ✅ 存在时 `ok=true`、`duration>0`、`voices>0`；✅ 不存在时构建脚本与 workflow 自检契约完备；✅ 两种情况都不得跳过断言。
**通过/失败**: 自检 `ok=false` 或契约缺失为失败。
**潜在缺陷**: PyInstaller 改写 `DYLD_*` 导致系统 `say` 在冻结进程内失效。

### TC-PKG-004: 无中文音色时自检应降级而非失败
**优先级**: P1　**类型**: 兼容性 / 边界　**预估**: 1 min
**前置条件**: 桩使 `choose_voice()` 返回 None，`list_voices()` 返回仅含英文音色的列表。
**测试步骤**: 1. 调用 `src.main.self_test()`；2. 捕获 stdout 与 `/tmp/docreader_selftest.json`；3. 检查返回值与 `ok` 字段。
**预期结果**: ✅ 自动回退到任一可用系统音色；✅ 仍能合成出音频且 `ok=true`；✅ 结果中标注 `fallback=true` 便于排查；✅ 仅在完全无音色时才返回非零退出码。
**通过/失败**: 返回 `ok=false` / 抛异常 / 直接报「没有中文语音」而没有降级，判失败。
**潜在缺陷**: GitHub macOS runner 未下载中文音色，导致 CI 自检失败、Release 无法产出。

### TC-PKG-005: GitHub Actions 工作流契约
**优先级**: P1　**类型**: 静态契约　**预估**: 1 min
**前置条件**: `.github/workflows/*.yml` 存在。
**测试步骤**: 1. 解析 YAML；2. 检查触发器、runner、权限、步骤顺序；3. 检查产物上传与 Release。
**预期结果**: ✅ `on.push.tags` 含 `v*`，且有 `workflow_dispatch`；✅ `runs-on: macos-latest`；✅ `permissions.contents: write`；✅ 质量门禁步骤排在打包之前；✅ 含 Artifact 上传与 Release 创建；✅ 使用 `actions/checkout@v4` 与 `setup-python`。
**通过/失败**: 触发器或步骤顺序错误为失败。
**潜在缺陷**: 忘记 `contents: write` 导致 Release 创建 403。

### TC-PKG-006: 仓库不携带大文件与本地状态
**优先级**: P2　**类型**: 静态契约　**预估**: 1 min
**前置条件**: `.gitignore` 存在。
**测试步骤**: 1. 检查 `.venv/`、`dist/`、`build/`、`__pycache__/`、`*.pyc`、`.pytest_cache/`、`.coverage`、`.build.log`、`.qa-deps.log`、`.pyinstaller-config/` 均被忽略；2. 确认 `src/`、`tests/docs/`、`samples/`、workflow 不被忽略。
**预期结果**: ✅ 全部构建产物与本地状态被排除；✅ 源码、用例文档、样例与流水线文件保留；✅ 仓库内无 `state.json` / `*.aiff`。
**通过/失败**: 任一忽略规则缺失为失败。
**潜在缺陷**: 182 MB 的 `.app` 或 `.venv` 被提交导致 push 失败。
