#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""批量预检对话框"""

from pathlib import Path
from typing import List, Dict

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from .processor import FormulaPreviewer


class BatchScanWorker(QThread):
    progress = pyqtSignal(int, str)
    file_scanned = pyqtSignal(int, dict)
    finished = pyqtSignal(list)
    
    def __init__(self, files: List[Path], config: Dict):
        super().__init__()
        self.files = files
        self.config = config
        self._is_stopped = False
    
    def stop(self):
        self._is_stopped = True
    
    def run(self):
        results = []
        previewer = FormulaPreviewer(self.config)
        
        for i, file_path in enumerate(self.files):
            if self._is_stopped:
                break
            
            self.progress.emit(i + 1, f"扫描中... {file_path.name}")
            
            try:
                text = file_path.read_text(encoding='utf-8')
                changes = previewer.preview(text, file_path)
                
                risk_counts = {'low': 0, 'medium': 0, 'high': 0}
                for c in changes:
                    risk_counts[c.risk_level] = risk_counts.get(c.risk_level, 0) + 1
                
                result = {
                    'file': file_path,
                    'changes': changes,
                    'total': len(changes),
                    'high': risk_counts['high'],
                    'medium': risk_counts['medium'],
                    'low': risk_counts['low'],
                }
            except Exception as e:
                result = {
                    'file': file_path,
                    'changes': [],
                    'total': 0,
                    'high': 0, 'medium': 0, 'low': 0,
                    'error': str(e),
                }
            
            results.append(result)
            self.file_scanned.emit(i, result)
        
        self.finished.emit(results)


class BatchPreviewDialog(QDialog):
    """批量预检摘要对话框"""
    
    def __init__(self, files: List[Path], config: Dict, parent=None):
        super().__init__(parent)
        self.files = files
        self.config = config
        self.results = []
        self.setWindowTitle("🔍 批量预检摘要")
        self.setMinimumSize(700, 450)
        self._setup_ui()
        self._start_scan()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # 进度
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(len(self.files))
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel(f"共 {len(self.files)} 个文件，准备扫描...")
        layout.addWidget(self.status_label)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["文件", "变更数", "🔴高风险", "🟡中风险", "🟢低风险"])
        self.table.setRowCount(len(self.files))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        self.table.setAlternatingRowColors(True)
        
        # 预填充文件名
        for i, f in enumerate(self.files):
            self.table.setItem(i, 0, QTableWidgetItem(f.name))
            for j in range(1, 5):
                self.table.setItem(i, j, QTableWidgetItem("—"))
        
        layout.addWidget(self.table)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        
        self.preview_selected_btn = QPushButton("🔍 预览选中")
        self.preview_selected_btn.clicked.connect(self._preview_selected)
        self.preview_selected_btn.setEnabled(False)
        btn_layout.addWidget(self.preview_selected_btn)
        
        self.preview_all_btn = QPushButton("📋 全部预览")
        self.preview_all_btn.clicked.connect(self._preview_all)
        self.preview_all_btn.setEnabled(False)
        btn_layout.addWidget(self.preview_all_btn)
        
        self.skip_no_change_btn = QPushButton("⏭️ 跳过无变更")
        self.skip_no_change_btn.clicked.connect(self._preview_all_skip_no_change)
        self.skip_no_change_btn.setEnabled(False)
        btn_layout.addWidget(self.skip_no_change_btn)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def _start_scan(self):
        self.progress_bar.setVisible(True)
        self.worker = BatchScanWorker(self.files, self.config)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_scanned.connect(self._on_file_scanned)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()
    
    def _on_progress(self, current, message):
        self.progress_bar.setValue(current)
        self.status_label.setText(message)
    
    def _on_file_scanned(self, index, result):
        self.results.append(result)
        
        row = index
        total = result['total']
        
        if 'error' in result:
            self.table.setItem(row, 1, QTableWidgetItem("错误"))
            return
        
        # 变更数
        count_item = QTableWidgetItem(str(total))
        if total > 10:
            count_item.setForeground(QColor("#e74c3c"))
            count_item.setFont(QFont(self.table.font().family(), -1, QFont.Weight.Bold))
        elif total > 0:
            count_item.setForeground(QColor("#e67e22"))
        count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 1, count_item)
        
        # 风险分布
        for col, key in [(2, 'high'), (3, 'medium'), (4, 'low')]:
            val = result[key]
            item = QTableWidgetItem(str(val) if val > 0 else "—")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if val > 0 and key == 'high':
                item.setForeground(QColor("#e74c3c"))
            self.table.setItem(row, col, item)
    
    def _on_finished(self, results):
        self.progress_bar.setVisible(False)
        self.results = results  # ★ 保存完整结果（之前只在 _on_file_scanned 中追加）
        
        with_changes = sum(1 for r in results if r['total'] > 0)
        without = len(results) - with_changes
        self.status_label.setText(
            f"扫描完成：{with_changes} 个有变更，{without} 个无变更"
        )
        
        has_changes = with_changes > 0
        self.preview_selected_btn.setEnabled(has_changes)
        self.preview_all_btn.setEnabled(has_changes)
        self.skip_no_change_btn.setEnabled(has_changes)
        
        # ★ 断开信号，释放 worker
        if hasattr(self, 'worker'):
            self.worker.progress.disconnect()
            self.worker.file_scanned.disconnect()
            self.worker.finished.disconnect()


        
        has_changes = with_changes > 0
        self.preview_selected_btn.setEnabled(has_changes)
        self.preview_all_btn.setEnabled(has_changes)
        self.skip_no_change_btn.setEnabled(has_changes)
    
    def _on_row_double_clicked(self, row, col):
        self._preview_row(row)
    
    def _preview_row(self, row):
        if 0 <= row < len(self.results):
            result = self.results[row]
            if result['total'] > 0:
                from .dialogs import SideBySidePreviewDialog
                
                # 先关闭批量摘要对话框
                self.accept()
                
                # 再打开预览
                dialog = SideBySidePreviewDialog(
                    result['changes'], None,
                    file_name=str(result['file'])
                )
                dialog.set_config(self.config)
                dialog.exec()
    
    def _preview_selected(self):
        rows = set(item.row() for item in self.table.selectedItems())
        for row in sorted(rows):
            self._preview_row(row)
    
    def _preview_all(self):
        results_to_preview = [r for r in self.results if r['total'] > 0]
        if not results_to_preview:
            return
        
        # 关闭摘要窗口
        self.accept()
        
        for result in results_to_preview:
            from .dialogs import SideBySidePreviewDialog
            dialog = SideBySidePreviewDialog(
                result['changes'], None,
                file_name=str(result['file'])
            )
            dialog.set_config(self.config)
            dialog.exec()

    def _preview_all_skip_no_change(self):
        self._preview_all()  # 逻辑一样——只预览有变更的
    
    def closeEvent(self, event):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            self.worker.quit()
            self.worker.wait(3000)
        super().closeEvent(event)

    def reject(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            self.worker.quit()
            self.worker.wait(3000)
        super().reject()