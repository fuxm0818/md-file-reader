"""QA harness: isolated state, real system speech, and per-test CSV tracking.

Ground truth = tests/docs/0*-TEST-CASES.md. This CSV is status only.
Every test result is appended the moment the test finishes (pytest hook).
"""
from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Only the full-suite runner (tests/run_qa.py) may write the tracking CSV.
# Ad-hoc single-test debugging must never wipe the release evidence.
FULL_RUN = os.environ.get("QA_FULL_RUN") == "1"

QA_DIR = ROOT / ".qa-workspace"
QA_STATE = QA_DIR / "state.json"
QA_CACHE = QA_DIR / "cache"
TRACKING_CSV = ROOT / "tests/docs/templates/TEST-EXECUTION-TRACKING.csv"
SAMPLE_DIR = ROOT / "samples"
SAMPLE_NAMES = ["示例文档.md", "示例文本.txt", "示例文档.docx", "示例文档.pdf"]
SAMPLE_PATHS = [str(SAMPLE_DIR / n) for n in SAMPLE_NAMES]

CSV_HEADERS = [
    "Test Case ID", "Category", "Priority", "Test Name",
    "Estimated Time (min)", "Prerequisites", "Status",
    "Result", "Bug ID", "Execution Date", "Executed By",
    "Notes", "Screenshot/Log",
]

# (category, priority, test name, estimated minutes)
CASE_CATALOG = {
    "TC-CORE-001": ("Core", "P0", "Markdown 解析为段落→句子模型并跳过代码块", 2),
    "TC-CORE-002": ("Core", "P0", "纯文本解析与多编码回退", 1),
    "TC-CORE-003": ("Core", "P0", "Word 文档保留标题层级与表格", 2),
    "TC-CORE-004": ("Core", "P0", "PDF 文字层提取与页码过滤", 2),
    "TC-CORE-005": ("Core", "P1", "扫描版 PDF 无文字层时返回明确错误", 1),
    "TC-CORE-006": ("Core", "P1", "不存在文件与空文件的容错", 1),
    "TC-CORE-007": ("Core", "P1", "Markdown 行内标记清洗规则", 1),
    "TC-CORE-008": ("Core", "P1", "句子切分与长句按软标点拆分", 1),
    "TC-CORE-009": ("Core", "P1", "展示文本与朗读句子的坐标一致性", 1),
    "TC-CORE-010": ("Core", "P1", "语速标定换算公式", 1),
    "TC-CORE-011": ("Core", "P0", "逐句真实语音合成与缓存命中", 3),
    "TC-CORE-012": ("Core", "P1", "音色探测与中文优先选择", 1),
    "TC-CORE-013": ("Core", "P1", "子进程环境清理", 1),
    "TC-CORE-014": ("Core", "P1", "afinfo 时长解析兼容性", 1),
    "TC-CORE-015": ("Core", "P0", "双坐标时间轴的估算→真实校准→反查", 1),
    "TC-CORE-016": ("Core", "P1", "时间轴边界与空文档", 1),
    "TC-CORE-017": ("Core", "P0", "播放列表 CRUD 与顺序管理", 2),
    "TC-CORE-018": ("Core", "P0", "断点写入、读取与文档变更失效", 2),
    "TC-CORE-019": ("Core", "P1", "状态文件原子保存与损坏回退", 1),
    "TC-CORE-020": ("Core", "P2", "音频缓存清理与体积统计", 1),
    "TC-GUI-001": ("GUI", "P0", "打开文档并开始朗读", 3),
    "TC-GUI-002": ("GUI", "P0", "暂停与继续不跳句", 2),
    "TC-GUI-003": ("GUI", "P0", "拖动进度吸附到句子边界", 2),
    "TC-GUI-004": ("GUI", "P1", "点击正文任意句从这里开始朗读", 1),
    "TC-GUI-005": ("GUI", "P1", "±15 秒快进快退", 1),
    "TC-GUI-006": ("GUI", "P1", "上一句 / 下一句导航", 1),
    "TC-GUI-007": ("GUI", "P0", "播完自动切下一项与顺序模式收尾", 2),
    "TC-GUI-008": ("GUI", "P1", "四种播放模式", 2),
    "TC-GUI-009": ("GUI", "P0", "退出重开恢复断点并回退一句", 3),
    "TC-GUI-010": ("GUI", "P1", "扫描件跳过且不中断连播", 2),
    "TC-GUI-011": ("GUI", "P1", "设置项生效并持久化", 2),
    "TC-GUI-012": ("GUI", "P1", "后台估算标记不可用文档与估算时长", 2),
    "TC-GUI-013": ("GUI", "P2", "主窗口三栏组件与信号装配", 2),
    "TC-GUI-014": ("GUI", "P2", "停止与关闭不残留后台线程", 1),
    "TC-SEC-001": ("Security", "P0", "命令注入：恶意文档文本不得进入 shell", 2),
    "TC-SEC-002": ("Security", "P0", "路径遍历：缓存键不可控文件名", 1),
    "TC-SEC-003": ("Security", "P1", "动态库注入面：清理 DYLD / PYTHON 环境变量", 1),
    "TC-SEC-004": ("Security", "P1", "畸形与超大输入不崩溃", 2),
    "TC-SEC-005": ("Security", "P1", "错误信息不泄漏堆栈与绝对路径", 1),
    "TC-SEC-006": ("Security", "P1", "本地状态完整性与无密钥落盘", 2),
    "TC-SEC-007": ("Security", "P2", "依赖版本约束与离线依赖面", 1),
    "TC-SEC-008": ("Security", "P2", "默认配置安全", 1),
    "TC-SEC-009": ("Security", "P2", "数值边界钳制（资源耗尽防护）", 1),
    "TC-SEC-010": ("Security", "P2", "N/A 论证：无访问控制面", 1),
    "TC-SEC-011": ("Security", "P2", "N/A 论证：无认证会话", 1),
    "TC-SEC-012": ("Security", "P2", "N/A 论证：无 SSRF 出站面", 1),
    "TC-PKG-001": ("Packaging", "P0", "build.sh 构建契约", 1),
    "TC-PKG-002": ("Packaging", "P0", "依赖清单完整且可分环境复现", 1),
    "TC-PKG-003": ("Packaging", "P1", "打包产物存在、已签名且自检通过", 3),
    "TC-PKG-004": ("Packaging", "P1", "无中文音色时自检应降级而非失败", 1),
    "TC-PKG-005": ("Packaging", "P1", "GitHub Actions 工作流契约", 1),
    "TC-PKG-006": ("Packaging", "P2", "仓库不携带大文件与本地状态", 1),
}

_NODE_CASE: dict[str, str] = {}


def pytest_configure(config):
    config.addinivalue_line("markers", "case(case_id): QA test case ID (ground truth in tests/docs)")
    # Redirect all persistent state away from the user's real Library folder.
    import src.core.speech as speech_mod
    import src.core.store as store_mod

    QA_DIR.mkdir(parents=True, exist_ok=True)
    QA_CACHE.mkdir(parents=True, exist_ok=True)
    speech_mod.APP_DIR = QA_DIR
    speech_mod.CACHE_DIR = QA_CACHE
    store_mod.APP_DIR = QA_DIR
    store_mod.STATE_FILE = QA_STATE
    if FULL_RUN:
        _reset_tracking_csv()


def _reset_tracking_csv():
    TRACKING_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACKING_CSV, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(CSV_HEADERS)


def pytest_collection_modifyitems(items):
    for item in items:
        marker = item.get_closest_marker("case")
        if marker:
            case_id = marker.args[0]
            assert case_id in CASE_CATALOG, f"未登记的用例 ID: {case_id}"
            _NODE_CASE[item.nodeid] = case_id


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _append_result(report)


def _append_result(report):
    if not FULL_RUN:
        return
    case_id = _NODE_CASE.get(report.nodeid)
    if not case_id:
        return
    category, priority, name, minutes = CASE_CATALOG[case_id]
    outcome = report.outcome
    if report.when != "call" and outcome == "skipped":
        status, result = "Skipped", "⚠️ SKIPPED"
    elif report.when != "call":
        # A fixture/setup failure means the test body never ran: it must NOT
        # count towards the execution rate.
        status, result = "Error", "❌ FAILED"
    else:
        status = "Completed" if outcome in ("passed", "failed") else "Skipped"
        result = {"passed": "✅ PASSED", "failed": "❌ FAILED", "skipped": "⚠️ SKIPPED"}[outcome]
    note = "自动执行，断言全部通过" if outcome == "passed" else str(report.longrepr)[:300].replace("\n", " ")
    with open(TRACKING_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            case_id, category, priority, name, minutes,
            "offscreen Qt + 隔离 state.json", status, result, "",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Horizon QA Bot (pytest)", note, report.nodeid,
        ])


# ------------------------------------------------------------------ fixtures
import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session")
def voice():
    from src.core.speech import Voice, choose_voice, list_voices
    voices = list_voices()
    return choose_voice(voices) or (voices[0] if voices else Voice("Alex", "en_US"))


@pytest.fixture(scope="session")
def tts_text(voice):
    return "这是一句用于语音合成自检的中文文本。" if voice.is_chinese else "DocReader speech synthesis smoke test."


@pytest.fixture(scope="session")
def sample_audio(voice, tts_text):
    """One real system-synthesized AIFF shared by all playback tests."""
    from src.core.speech import SpeechEngine
    engine = SpeechEngine(voice, 200)
    path, duration, error = engine.synthesize(tts_text)
    assert path is not None and duration > 0, f"系统语音不可用: {error}"
    return path, max(duration, 1.0)


@pytest.fixture
def fresh_store():
    from src.core.store import Store
    if QA_STATE.exists():
        os.remove(QA_STATE)
    return Store()


@pytest.fixture
def make_controller(qapp, sample_audio, monkeypatch):
    """Controller with real Qt player but cached audio (fast, deterministic)."""
    import src.controller as controller_mod
    from src.controller import ReaderController
    from src.core.speech import SpeechEngine

    # GitHub macOS runners may not have a downloaded Chinese voice. The app
    # intentionally warns users in that case; for QA we fall back to any
    # available system voice so the playback chain stays testable.
    real_choose = controller_mod.choose_voice
    monkeypatch.setattr(
        controller_mod, "choose_voice",
        lambda voices, preferred="": real_choose(voices, preferred)
        or (voices[0] if voices else None),
    )
    audio = sample_audio
    monkeypatch.setattr(SpeechEngine, "calibrate", lambda self: 0.2)
    monkeypatch.setattr(SpeechEngine, "cached", lambda self, text: audio)
    created = []

    def factory(store, paths=None):
        if paths is not None:
            store.add_items(paths, None)
        c = ReaderController(store)
        c.audio.setVolume(0.0)
        created.append(c)
        return c

    yield factory
    for c in created:
        try:
            c.shutdown()
        except Exception:
            pass


@pytest.fixture
def controller(fresh_store, make_controller):
    return make_controller(fresh_store, SAMPLE_PATHS)


@pytest.fixture(scope="session")
def scan_pdf(qapp):
    """A PDF with a raster rectangle only: no text layer."""
    from PySide6.QtGui import QBrush, QColor, QPdfWriter, QPainter
    path = QA_DIR / "scan_no_text.pdf"
    writer = QPdfWriter(str(path))
    painter = QPainter(writer)
    painter.fillRect(60, 60, 400, 260, QBrush(QColor("#cccccc")))
    painter.end()
    return str(path)


def wait_ms(milliseconds: int) -> None:
    """Run the Qt event loop for a while so singleShot timers can fire."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def wait_until(predicate, timeout_s: float = 8.0) -> bool:
    """Poll a background-thread result while keeping Qt events flowing."""
    from PySide6.QtWidgets import QApplication
    end = time.time() + timeout_s
    while time.time() < end:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False
