"""生成 README 用的界面截图。

直接对真实应用截图会把用户自己的播放列表拍进去——那既泄露内容，也不
适合当项目门面。这里把状态目录和缓存都指到 `.qa-workspace/shot/`，只
放仓库自带的示例文档，截完就丢。

用法：
    QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/make_screenshot.py
产出：
    docs/screenshot.png
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHOT_DIR = ROOT / ".qa-workspace" / "shot"

# 截图用自己写的一段散文，不用 samples 里的测试样本：那份文档带代码块，
# 下划线会被 Markdown 当成斜体吃掉，截出来像是渲染有 bug。
SAMPLE_NAME = "阅读笔记.md"
SAMPLE_TEXT = """# 阅读笔记

## 一、为什么要在路上读

通勤的四十分钟，眼睛要盯着路，手要扶着栏杆，唯一闲下来的是耳朵。把书读成声音，这段时间就不再是纯粹的等待。

听和看是两回事。眼睛会跳读，会自动略过不重要的段落；耳朵不会，它只能一句一句往下走，所以听过的内容反而记得更牢。

## 二、边看边听

朗读的时候，正在读的那一句会在正文里高亮，并且自动滚到视野内。想回头重听某一句，双击它就行，程序会立刻从那里接着念。

进度条上的时间是按语速和字数换算出来的，不是真实时长。拖动进度条会吸附到句子边界，因为语音是一句一句合成的，不存在"从这一句的第三点八个字开始"。

## 三、把声音调顺

默认音色是系统自带的中文语音，不联网、不上传。合成之后会做一遍处理：去掉低频的嗡嗡声，首尾做淡入淡出避免爆音，再把整体响度对齐到统一水平，免得换一句就忽大忽小。

如果某一句听起来被截断了，多半是那句话太长，可以在设置里把语速调慢一点再试。
"""

EXTRA_DOCS = {
    "瓦尔登湖·节选.md": """# 瓦尔登湖·节选

我到林中去，是因为我希望谨慎地生活，只面对生活的基本事实，看看我是否学得到生活要教育我的东西，免得到了临死的时候，才发现我根本就没有生活过。

我不希望度过非生活的生活，生活是这样的可爱；我却也不愿意去修行过隐逸的生活，除非是万不得已。

我要生活得深深地把生命的精髓都吸到，要生活得稳稳当当，生活得斯巴达式的，以便根除一切非生活的东西，划出一块刈割的面积来，细细地刈割或修剪，把生活压缩到一个角隅里去，把它缩小到最低的条件中。
""",
    "如何做读书笔记.md": """# 如何做读书笔记

## 摘录不是笔记

把句子抄下来，只是搬运。真正有用的是写下你当时的反应：为什么这句让你停下来了，它和你已经知道的哪件事对上了，或者哪一点你不同意。

## 三个问题

读完一章，问自己三件事：作者想让我相信什么？他凭什么让我相信？我信了吗？

## 定期回看

笔记的价值在回看时才出现。隔一个月翻一遍，把已经不需要的划掉，把还成立的圈出来。留下来的那几条，才是你自己的。
""",
}


def _isolate() -> None:
    """把落盘位置整体挪到工作区的临时目录。"""
    import src.core.speech as speech_mod
    import src.core.store as store_mod

    for sub in ("", "cache"):
        (SHOT_DIR / sub).mkdir(parents=True, exist_ok=True)

    speech_mod.APP_DIR = SHOT_DIR
    speech_mod.CACHE_DIR = SHOT_DIR / "cache"
    store_mod.APP_DIR = SHOT_DIR
    store_mod.STATE_FILE = SHOT_DIR / "state.json"
    # 语音标定也走这个缓存目录，别去动真实缓存。
    if hasattr(speech_mod, "CALIBRATION_FILE"):
        speech_mod.CALIBRATION_FILE = SHOT_DIR / "calibration.json"


def main() -> int:
    _isolate()

    from PySide6.QtWidgets import QApplication

    from src.ui.main_window import MainWindow

    app = QApplication([])
    window = MainWindow()
    window.resize(1180, 780)
    window.show()

    sample = SHOT_DIR / SAMPLE_NAME
    sample.write_text(SAMPLE_TEXT, encoding="utf-8")
    others = []
    for name, text in EXTRA_DOCS.items():
        path = SHOT_DIR / name
        path.write_text(text, encoding="utf-8")
        others.append(str(path))
    # 第一个是截图主角，其余只用来把左栏填得像真实列表。
    window._add_paths([str(sample)], None)
    for path in others:
        window._add_paths([path], None)

    # 列表要等计时估算，正文要等解析，都是后台线程，靠事件循环推进。
    for _ in range(80):
        app.processEvents()
        time.sleep(0.03)

    window.controller.select_item(0, True)
    # 一直推进到正文段落，别让高亮停在标题上——标题只读半秒就过去了。
    for _ in range(400):
        app.processEvents()
        time.sleep(0.03)
        if window.controller.sentence_index >= 6:
            break
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)

    out = ROOT / "docs" / "screenshot.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    image = window.grab()
    image.save(str(out))
    print(f"{out.relative_to(ROOT)}: {image.width()}x{image.height()}")
    window.controller.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
