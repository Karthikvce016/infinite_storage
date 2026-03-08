"""
styles.py – Stylesheet definitions and UI styling constants for Telegram Drive.
"""

# Colour palette (dark-mode inspired)
BG = "#1e1e2e"
SURFACE = "#282840"
PRIMARY = "#7c3aed"
PRIMARY_LIGHT = "#a78bfa"
TEXT = "#e2e2f0"
TEXT_DIM = "#9898b0"
ACCENT = "#06d6a0"
DANGER = "#ef4444"
DROP_BORDER = "#7c3aed"
DROP_BORDER_ACTIVE = "#06d6a0"

STYLESHEET = f"""
    * {{
        font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', sans-serif;
    }}
    QMainWindow, QDialog {{
        background-color: {BG};
    }}
    QLabel {{
        color: {TEXT};
    }}
    QLineEdit {{
        background-color: {SURFACE};
        color: {TEXT};
        border: 1px solid #3a3a5c;
        border-radius: 6px;
        padding: 8px 12px;
        font-size: 14px;
    }}
    QLineEdit:focus {{
        border-color: {PRIMARY};
    }}
    QPushButton {{
        background-color: {PRIMARY};
        color: #ffffff;
        border: none;
        border-radius: 6px;
        padding: 10px 20px;
        font-size: 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {PRIMARY_LIGHT};
    }}
    QPushButton:pressed {{
        background-color: #6d28d9;
    }}
    QPushButton#dangerBtn {{
        background-color: {DANGER};
    }}
    QPushButton#secondaryBtn {{
        background-color: {SURFACE};
        border: 1px solid #3a3a5c;
    }}
    QPushButton#downloadBtn {{
        background-color: {ACCENT};
        color: #1e1e2e;
        padding: 4px 12px;
        font-size: 12px;
        border-radius: 4px;
    }}
    QPushButton#downloadBtn:hover {{
        background-color: #34d399;
    }}
    QPushButton#viewBtn {{
        background-color: #3b82f6;
        color: #ffffff;
        padding: 4px 12px;
        font-size: 12px;
        border-radius: 4px;
    }}
    QPushButton#viewBtn:hover {{
        background-color: #60a5fa;
    }}
    QProgressBar {{
        background-color: {SURFACE};
        border: none;
        border-radius: 6px;
        text-align: center;
        color: {TEXT};
        height: 22px;
        font-size: 12px;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {PRIMARY}, stop:1 {ACCENT}
        );
        border-radius: 6px;
    }}
    QTableWidget {{
        background-color: {SURFACE};
        color: {TEXT};
        border: none;
        border-radius: 8px;
        gridline-color: #3a3a5c;
        font-size: 13px;
    }}
    QTableWidget::item {{
        padding: 6px 10px;
    }}
    QHeaderView::section {{
        background-color: #2a2a48;
        color: {TEXT_DIM};
        border: none;
        padding: 8px 10px;
        font-weight: 600;
        font-size: 12px;
        text-transform: uppercase;
    }}
"""
