"""应用版本号的唯一真相源。

发版时只改这里：``build.sh`` 会把它写进 ``Info.plist``，界面「关于」面板与
自检输出也都读同一个值。此前版本号散落在打包脚本和测试入口里，打出来的
``.app`` 顶着 PyInstaller 的默认 ``0.0.0``，用户查不到自己装的是哪一版。
"""
from __future__ import annotations

__version__ = "1.4.0"

#: 形如 ``v1.4.0``，用于 tag、发布说明与自检输出。
VERSION_TAG = f"v{__version__}"
