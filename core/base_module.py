#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块基类定义
所有功能模块必须继承此基类并实现抽象方法
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Dict, Any, Callable
from pathlib import Path
from threading import Lock

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import pyqtSignal, QObject


class ModuleSignals(QObject):
    """模块信号集合
    
    信号说明:
        status_changed: 模块状态变化 (str: "ready" | "processing" | "error")
        progress_updated: 处理进度更新 (int: 百分比, str: 进度描述)
        log_message: 日志消息 (str: 消息内容, str: 日志级别)
    """
    status_changed = pyqtSignal(str)
    progress_updated = pyqtSignal(int, str)
    log_message = pyqtSignal(str, str)


class BaseModule(ABC):
    """所有功能模块的基类
    
    设计原则:
        1. 模板方法模式：定义处理流程骨架，子类实现具体步骤
        2. 信号驱动通信：通过 ModuleSignals 与 UI 层解耦
        3. 线程安全：is_processing 状态变更受锁保护
        
    子类必须实现:
        - module_id, module_name, module_icon, module_description (属性)
        - accepted_extensions (属性)
        - create_ui(), check_dependencies(), start_processing(), stop_processing() (方法)
    """
    
    def __init__(self):
        self.signals = ModuleSignals()
        self._ui_widget: Optional[QWidget] = None
        self._is_processing = False
        self._state_lock = Lock()  # ★ 新增：状态锁，保证线程安全
    
    # ==================== 必须实现的抽象属性/方法 ====================
    
    @property
    @abstractmethod
    def module_id(self) -> str:
        """模块唯一标识符（用于内部识别）
        
        示例: "md_repair", "md2epub", "epub2pdf", "workflow"
        """
        pass
    
    @property
    @abstractmethod
    def module_name(self) -> str:
        """模块显示名称（用于 UI 展示）
        
        示例: "📝 MD公式修复", "📖 MD转EPUB"
        """
        pass
    
    @property
    @abstractmethod
    def module_icon(self) -> str:
        """模块图标（emoji 或资源路径）
        
        示例: "📝", ":/icons/repair.png"
        """
        pass
    
    @property
    @abstractmethod
    def module_description(self) -> str:
        """模块功能描述（用于提示信息）"""
        pass
    
    @property
    @abstractmethod
    def accepted_extensions(self) -> List[str]:
        """支持的文件扩展名列表
        
        示例: ['.md'], ['.epub'], ['.md', '.txt']
        """
        pass
    
    @abstractmethod
    def create_ui(self, parent=None) -> QWidget:
        """创建模块的 UI 界面（由基类惰性调用，仅创建一次）
        
        Args:
            parent: 父级 QWidget
            
        Returns:
            QWidget: 模块的主界面组件
        """
        pass
    
    @abstractmethod
    def check_dependencies(self) -> Tuple[bool, str]:
        """检查模块依赖是否满足
        
        Returns:
            Tuple[bool, str]: (依赖是否满足, 状态描述信息)
            
        示例:
            return True, "Pandoc 3.1.12 已安装"
            return False, "未找到 Pandoc，请安装后重试"
        """
        pass
    
    @abstractmethod
    def start_processing(self, files: List[Path], **kwargs) -> bool:
        """开始处理文件（子类应在此方法中启动 Worker 线程）
        
        Args:
            files: 要处理的文件列表
            **kwargs: 额外参数（输出目录、设置等）
            
        Returns:
            bool: 是否成功启动处理
            
        注意:
            子类实现应:
            1. 检查 is_processing 状态，防止重复启动
            2. 设置 is_processing = True
            3. 创建并启动 Worker 线程
            4. 连接 Worker 完成信号以恢复状态
        """
        pass
    
    @abstractmethod
    def stop_processing(self):
        """停止当前处理（子类应实现优雅终止逻辑）
        
        注意:
            1. 应设置 Worker 的取消标志，而非强制 kill
            2. 应等待 Worker 线程合理退出
            3. 退出后设置 is_processing = False
        """
        pass
    
    # ==================== 可选重写的方法 ====================
    
    def get_settings_ui(self, parent=None) -> Optional[QWidget]:
        """获取模块特有的设置 UI（显示在主窗口右侧设置面板）
        
        Returns:
            Optional[QWidget]: 设置组件，None 表示无额外设置
        """
        return None
    
    def get_toolbar_actions(self) -> List[Tuple[str, str, Callable]]:
        """获取模块特有的工具栏动作
        
        Returns:
            List[Tuple[str, str, Callable]]: [(图标, 文本, 回调函数), ...]
        """
        return []
    
    def on_activate(self):
        """模块被激活时调用（切换到此模块时触发）
        
        子类可重写以执行初始化逻辑，如刷新文件列表、更新 UI 状态等。
        """
        pass
    
    def on_deactivate(self):
        """模块被停用时调用（切换到其他模块时触发）
        
        子类可重写以执行清理逻辑。
        """
        pass
    
    def can_process(self) -> bool:
        """检查当前是否可以开始处理
        
        Returns:
            bool: 未在处理中且依赖满足时返回 True
            
        子类可重写以添加额外检查（如文件列表非空等）。
        """
        return not self.is_processing
    
    def clear_all_files(self):
        """清空当前模块的文件列表（由 Ctrl+Shift+Q 快捷键触发）
        
        子类若没有 file_list 属性，默认不做任何操作。
        有 file_list 的子类也不需要重写，基类通过 hasattr 自动适配。
        """
        if hasattr(self, 'file_list'):
            count = self.file_list.count()
            if count > 0:
                self.file_list.clear_all()
                self.log(f"🗑️ 已清空文件列表（共 {count} 个），快捷键 Ctrl+Shift+Q", "INFO")
    
    # ==================== 状态管理（线程安全） ====================
    
    @property
    def is_processing(self) -> bool:
        """是否正在处理中（线程安全）
        
        Returns:
            bool: True 表示正在处理，False 表示空闲
        """
        with self._state_lock:
            return self._is_processing
    
    @is_processing.setter
    def is_processing(self, value: bool):
        """设置处理状态（线程安全）
        
        状态变更会自动发出 status_changed 信号。
        
        Args:
            value: True = 处理中，False = 空闲
        """
        with self._state_lock:
            old_value = self._is_processing
            self._is_processing = value
        
        # 仅在状态真的发生变化时才发出信号
        if old_value != value:
            self.signals.status_changed.emit("processing" if value else "ready")
    
    # ==================== UI 管理 ====================
    
    @property
    def ui_widget(self) -> Optional[QWidget]:
        """获取 UI 组件（惰性创建，仅创建一次）
        
        Returns:
            Optional[QWidget]: 模块的主界面组件
        """
        if self._ui_widget is None:
            self._ui_widget = self.create_ui()
        return self._ui_widget
    
    # ==================== 信号便捷方法 ====================
    
    def log(self, message: str, level: str = "INFO"):
        """发送日志消息
        
        Args:
            message: 日志内容
            level: 日志级别，建议使用 "INFO", "WARN", "ERROR", "DEBUG"
        """
        self.signals.log_message.emit(message, level.upper())
    
    def update_progress(self, percent: int, message: str = ""):
        """更新处理进度（0-100）
        
        Args:
            percent: 进度百分比（0-100）
            message: 进度说明文本
        """
        # 确保百分比在有效范围内
        percent = max(0, min(100, percent))
        self.signals.progress_updated.emit(percent, message)


# ==================== 元信息 ====================
__author__ = "YQJ"
__version__ = "1.1.0"  # ★ 更新版本号
__date__ = "2026.05.05"  # ★ 更新日期