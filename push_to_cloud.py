#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 docs/data.json 推送为小程序可用的数据源。

【生产环境：微信云开发云存储】
  1. npm i -g @cloudbase/cli          # 安装 tcb 命令行
  2. tcb login                        # 浏览器扫码登录
  3. 设置环境变量：
       export CLOUD_ENV=你的云环境ID   # 在「云开发」控制台查看
       export CLOUD_FILE_PATH=data/data.json   # 云存储对象路径（默认即可）
  4. python3 push_to_cloud.py

【未配置 CLOUD_ENV 时】
  仅更新 miniprogram/data/mock.js（离线预览副本），小程序在开发者工具里可直接看数据，
  无需任何云端配置。
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "docs", "data.json")
MOCK = os.path.join(ROOT, "miniprogram", "data", "mock.js")
CLOUD_ENV = os.environ.get("CLOUD_ENV", "")
CLOUD_PATH = os.environ.get("CLOUD_FILE_PATH", "data/data.json")


def update_mock():
    with open(SRC, encoding="utf-8") as f:
        data = json.load(f)
    with open(MOCK, "w", encoding="utf-8") as f:
        f.write("// 离线预览用数据副本（由 push_to_cloud.py 自动生成，勿手改）\n")
        f.write("module.exports = ")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print("已更新本地离线副本:", MOCK)


def push_cloud():
    cli = None
    for cand in ("tcb", "cloudbase"):
        if shutil.which(cand):
            cli = cand
            break
    if not cli:
        print("未找到 tcb/cloudbase CLI，请先执行：npm i -g @cloudbase/cli && tcb login")
        return False
    cmd = [cli, "storage", "upload", SRC, CLOUD_PATH, "-e", CLOUD_ENV]
    print("执行:", " ".join(cmd))
    return subprocess.run(cmd).returncode == 0


if __name__ == "__main__":
    update_mock()
    if CLOUD_ENV:
        if push_cloud():
            print("✅ 已推送到云存储环境:", CLOUD_ENV)
        else:
            print("⚠️ 云存储推送失败，已保留本地离线副本（小程序仍可用 mock 数据预览）")
            sys.exit(1)
    else:
        print("ℹ️ 未设置 CLOUD_ENV，仅更新本地离线副本；生产环境请配置云开发环境后重跑。")
