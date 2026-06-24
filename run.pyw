"""
南理工课表管理系统 — 无控制台启动入口
双击此文件直接运行，不显示命令行窗口。
"""
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main
