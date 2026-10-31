#!/bin/bash
# macOS：双击这个文件启动 LifeOS（iPhone 模式）。关掉窗口即停止。
cd "$(dirname "$0")"
python3 -m lifeos phone
