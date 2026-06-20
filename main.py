"""
🎵 檔案排序與命名工具 - Android 版
=====================================
功能：
  - 開啟手機內部儲存資料夾
  - ☰ 拖曳把手調整播放順序
  - 點 # 欄輸入編號直接跳轉
  - 點 ✏ 修改單一檔案名稱
  - 即時預覽最終檔名
  - 執行批次更名

需求：Python 3.8+ / Kivy 2.2+
"""

import re
import os
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import (
    StringProperty, BooleanProperty, NumericProperty, ObjectProperty
)
from kivy.uix.behaviors import DragBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, Line
from kivy.animation import Animation
from kivy.core.window import Window

# Android 權限（打包後生效，桌面執行時略過）
try:
    from android.permissions import request_permissions, Permission  # type: ignore
    from android.storage import primary_external_storage_path        # type: ignore
    IS_ANDROID = True
except ImportError:
    IS_ANDROID = False


# ═══════════════════════════════════════════════════════════
#  顏色常數
# ═══════════════════════════════════════════════════════════
BG       = (0.118, 0.118, 0.180, 1)   # #1e1e2e
SURF     = (0.165, 0.165, 0.243, 1)   # #2a2a3e
SURF2    = (0.180, 0.180, 0.267, 1)   # #2e2e44
ACC      = (0.486, 0.416, 0.969, 1)   # #7c6af7
ACC_D    = (0.400, 0.333, 0.839, 1)   # darker accent
FG       = (0.804, 0.839, 0.957, 1)   # #cdd6f4
FG_DIM   = (0.533, 0.537, 0.667, 1)   # dimmed text
LINE_COL = (0.651, 0.890, 0.631, 1)   # #a6e3a1 green
ROW_ODD  = (0.180, 0.180, 0.267, 1)
ROW_EVEN = (0.165, 0.165, 0.243, 1)
RED      = (0.961, 0.384, 0.384, 1)
WHITE    = (1, 1, 1, 1)


def hex_to_kivy(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4)) + (1,)


# ═══════════════════════════════════════════════════════════
#  資料模型
# ═══════════════════════════════════════════════════════════
class FileItem:
    _PREFIX_RE = re.compile(r"^\d+[^a-zA-Z\u4e00-\u9fff]+")

    def __init__(self, path: Path):
        self.path          = path
        self.suffix        = path.suffix
        clean              = self._strip_prefix(path.stem)
        self.original_name = clean
        self.custom_name   = clean

    @classmethod
    def _strip_prefix(cls, stem: str) -> str:
        return cls._PREFIX_RE.sub("", stem).strip() or stem

    @property
    def final_name(self) -> str:
        return self.custom_name + self.suffix


# ═══════════════════════════════════════════════════════════
#  共用工具
# ═══════════════════════════════════════════════════════════
def nkey(s: str):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", s)]


def make_bg(widget, color):
    """為 widget 添加純色背景。"""
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda w, v: setattr(rect, "pos", v),
                size=lambda w, v: setattr(rect, "size", v))
    return rect


# ═══════════════════════════════════════════════════════════
#  自訂元件：帶背景色的 BoxLayout
# ═══════════════════════════════════════════════════════════
class ColorBox(BoxLayout):
    bg_color = (0, 0, 0, 0)

    def __init__(self, bg_color=None, **kw):
        super().__init__(**kw)
        if bg_color:
            self.bg_color = bg_color
        with self.canvas.before:
            Color(*self.bg_color)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update, size=self._update)

    def _update(self, *_):
        self._rect.pos  = self.pos
        self._rect.size = self.size


# ═══════════════════════════════════════════════════════════
#  插入線 Widget
# ═══════════════════════════════════════════════════════════
class InsertLine(Widget):
    def __init__(self, **kw):
        super().__init__(size_hint_y=None, height=dp(2), **kw)
        with self.canvas:
            Color(*LINE_COL)
            self._line = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._line.pos  = self.pos
        self._line.size = self.size


# ═══════════════════════════════════════════════════════════
#  單列 Widget（含拖曳把手 ☰）
# ═══════════════════════════════════════════════════════════
class FileRow(ColorBox):
    """
    佈局（左→右）：
      [☰ 把手 40dp] [# 編號 60dp] [檔名（彈性）] [✏ 按鈕 44dp]
    """

    def __init__(self, item: FileItem, index: int, app_ref, **kw):
        super().__init__(
            bg_color=ROW_ODD if index % 2 else ROW_EVEN,
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            **kw
        )
        self.item    = item
        self.index   = index
        self.app_ref = app_ref
        self._dragging   = False
        self._touch_offset_y = 0

        # ── 拖曳把手 ☰ ──────────────────────────────────
        self.handle = Label(
            text="☰",
            size_hint=(None, 1),
            width=dp(44),
            font_size=dp(22),
            color=FG_DIM,
            halign="center",
        )
        self.add_widget(self.handle)

        # ── 編號欄（可點擊輸入） ─────────────────────────
        self.num_btn = Button(
            text=self._fmt_num(),
            size_hint=(None, 1),
            width=dp(62),
            font_size=dp(13),
            bold=True,
            background_normal="",
            background_color=(0, 0, 0, 0),
            color=ACC,
        )
        self.num_btn.bind(on_release=lambda *_: self.app_ref.open_num_input(self))
        self.add_widget(self.num_btn)

        # ── 檔名標籤 ────────────────────────────────────
        self.name_lbl = Label(
            text=self._preview_text(),
            size_hint=(1, 1),
            font_size=dp(13),
            color=FG,
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
            text_size=(None, None),
        )
        self.name_lbl.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))
        self.add_widget(self.name_lbl)

        # ── 編輯按鈕 ✏ ──────────────────────────────────
        edit_btn = Button(
            text="✏",
            size_hint=(None, 1),
            width=dp(44),
            font_size=dp(18),
            background_normal="",
            background_color=(0, 0, 0, 0),
            color=FG_DIM,
        )
        edit_btn.bind(on_release=lambda *_: self.app_ref.open_rename_popup(self))
        self.add_widget(edit_btn)

        # 分隔線
        with self.canvas.after:
            Color(0.25, 0.25, 0.35, 1)
            self._sep = Line(points=[0, 0, 0, 0], width=dp(0.5))
        self.bind(pos=self._draw_sep, size=self._draw_sep)

    def _draw_sep(self, *_):
        self._sep.points = [self.x, self.y, self.x + self.width, self.y]

    def _fmt_num(self) -> str:
        app = self.app_ref
        return str(app.start_num + self.index).zfill(app.pad_digits)

    def _preview_text(self) -> str:
        app  = self.app_ref
        num  = self._fmt_num()
        sep  = app.separator
        return f"{num}{sep}{self.item.final_name}"

    def refresh(self, index: int):
        """更新索引後刷新顯示。"""
        self.index = index
        self.bg_color = ROW_ODD if index % 2 else ROW_EVEN
        with self.canvas.before:
            Color(*self.bg_color)
            self._rect.pos  = self.pos
            self._rect.size = self.size
        self.num_btn.text  = self._fmt_num()
        self.name_lbl.text = self._preview_text()

    # ── 觸控事件（拖曳把手區域才觸發） ─────────────────────

    def on_touch_down(self, touch):
        # 只有碰到 handle 區域才啟動拖曳
        if self.handle.collide_point(*touch.pos):
            touch.grab(self)
            self._dragging = True
            self._touch_offset_y = touch.y - self.y
            self.app_ref.on_drag_start(self, touch)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self and self._dragging:
            self.app_ref.on_drag_move(self, touch)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self and self._dragging:
            touch.ungrab(self)
            self._dragging = False
            self.app_ref.on_drag_end(self, touch)
            return True
        return super().on_touch_up(touch)


# ═══════════════════════════════════════════════════════════
#  檔案瀏覽 Popup（選擇資料夾）
# ═══════════════════════════════════════════════════════════
class FolderBrowserPopup(Popup):
    def __init__(self, start_path: str, on_select, **kw):
        super().__init__(
            title="選擇資料夾",
            size_hint=(0.95, 0.85),
            background_color=SURF,
            **kw
        )
        self.on_select_cb = on_select
        self.current_path = Path(start_path)

        layout = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(8))

        # 目前路徑顯示
        self.path_lbl = Label(
            text=str(self.current_path),
            size_hint_y=None, height=dp(36),
            font_size=dp(12), color=FG_DIM,
            halign="left", valign="middle",
            shorten=True, shorten_from="left",
        )
        self.path_lbl.bind(size=lambda w, s: setattr(w, "text_size", s))
        layout.add_widget(self.path_lbl)

        # 返回上層按鈕
        up_btn = Button(
            text="⬆  上一層",
            size_hint_y=None, height=dp(44),
            background_normal="", background_color=SURF2,
            color=FG, font_size=dp(14),
        )
        up_btn.bind(on_release=lambda *_: self._go_up())
        layout.add_widget(up_btn)

        # 資料夾清單
        scroll = ScrollView(size_hint=(1, 1))
        self.folder_list = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        self.folder_list.bind(minimum_height=self.folder_list.setter("height"))
        scroll.add_widget(self.folder_list)
        layout.add_widget(scroll)

        # 底部：選擇此資料夾 + 取消
        bot = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        cancel_btn = Button(
            text="取消",
            background_normal="", background_color=SURF2, color=FG,
            font_size=dp(14),
        )
        cancel_btn.bind(on_release=lambda *_: self.dismiss())
        select_btn = Button(
            text="✅ 選擇此資料夾",
            background_normal="", background_color=ACC, color=WHITE,
            font_size=dp(14), bold=True,
        )
        select_btn.bind(on_release=lambda *_: self._select_current())
        bot.add_widget(cancel_btn)
        bot.add_widget(select_btn)
        layout.add_widget(bot)

        self.content = layout
        self._populate()

    def _populate(self):
        self.folder_list.clear_widgets()
        self.path_lbl.text = str(self.current_path)
        try:
            entries = sorted(
                [e for e in self.current_path.iterdir() if e.is_dir()],
                key=lambda p: p.name.lower()
            )
        except PermissionError:
            entries = []

        for entry in entries:
            btn = Button(
                text=f"📁  {entry.name}",
                size_hint_y=None, height=dp(48),
                background_normal="", background_color=SURF,
                color=FG, font_size=dp(14),
                halign="left", valign="middle",
            )
            btn.text_size = (Window.width * 0.85, None)
            entry_path = entry
            btn.bind(on_release=lambda b, p=entry_path: self._enter(p))
            self.folder_list.add_widget(btn)

    def _enter(self, path: Path):
        self.current_path = path
        self._populate()

    def _go_up(self):
        parent = self.current_path.parent
        if parent != self.current_path:
            self.current_path = parent
            self._populate()

    def _select_current(self):
        self.on_select_cb(str(self.current_path))
        self.dismiss()


# ═══════════════════════════════════════════════════════════
#  主 APP
# ═══════════════════════════════════════════════════════════
class RenameApp(App):

    # 設定
    start_num  = 1
    pad_digits = 2
    separator  = " - "
    ext_filter = ""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.items:       list[FileItem] = []
        self.folder:      Path | None    = None
        self.rows:        list[FileRow]  = []

        # 拖曳狀態
        self._drag_row:       FileRow | None = None
        self._ghost:          Label | None   = None
        self._insert_line:    InsertLine | None = None
        self._drag_target_idx: int = -1

    def build(self):
        if IS_ANDROID:
            request_permissions([
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.MANAGE_EXTERNAL_STORAGE,
            ])

        Window.clearcolor = BG

        # ── 根佈局 ──────────────────────────────────────
        self.root_layout = FloatLayout()

        # 主內容（垂直）
        main = BoxLayout(orientation="vertical", size_hint=(1, 1))
        self.root_layout.add_widget(main)

        # ── 頂部標題列 ──────────────────────────────────
        header = ColorBox(bg_color=SURF, orientation="horizontal",
                          size_hint_y=None, height=dp(56), padding=[dp(12), 0])
        title = Label(text="🎵 檔案排序工具", font_size=dp(18), bold=True,
                      color=ACC, size_hint=(1, 1), halign="left", valign="middle")
        title.bind(size=lambda w, s: setattr(w, "text_size", s))
        header.add_widget(title)

        open_btn = Button(
            text="📁 開啟",
            size_hint=(None, None), width=dp(90), height=dp(40),
            background_normal="", background_color=ACC,
            color=WHITE, font_size=dp(14), bold=True,
        )
        open_btn.bind(on_release=lambda *_: self._open_folder_browser())
        header.add_widget(open_btn)
        main.add_widget(header)

        # ── 設定列 ──────────────────────────────────────
        cfg = ColorBox(bg_color=SURF2, orientation="horizontal",
                       size_hint_y=None, height=dp(44),
                       padding=[dp(8), 0], spacing=dp(8))

        cfg.add_widget(Label(text="起始#", font_size=dp(12), color=FG_DIM,
                             size_hint=(None, 1), width=dp(42)))
        self.start_input = TextInput(
            text="1", multiline=False, font_size=dp(13),
            size_hint=(None, None), width=dp(40), height=dp(32),
            background_color=SURF, foreground_color=FG,
            cursor_color=FG, halign="center",
        )
        self.start_input.bind(on_text_validate=self._apply_settings,
                              focus=lambda w, v: (not v) and self._apply_settings())
        cfg.add_widget(self.start_input)

        cfg.add_widget(Label(text="補零", font_size=dp(12), color=FG_DIM,
                             size_hint=(None, 1), width=dp(32)))
        self.pad_input = TextInput(
            text="2", multiline=False, font_size=dp(13),
            size_hint=(None, None), width=dp(32), height=dp(32),
            background_color=SURF, foreground_color=FG,
            cursor_color=FG, halign="center",
        )
        self.pad_input.bind(on_text_validate=self._apply_settings,
                            focus=lambda w, v: (not v) and self._apply_settings())
        cfg.add_widget(self.pad_input)

        cfg.add_widget(Label(text="分隔", font_size=dp(12), color=FG_DIM,
                             size_hint=(None, 1), width=dp(32)))
        self.sep_input = TextInput(
            text=" - ", multiline=False, font_size=dp(13),
            size_hint=(None, None), width=dp(52), height=dp(32),
            background_color=SURF, foreground_color=FG,
            cursor_color=FG,
        )
        self.sep_input.bind(on_text_validate=self._apply_settings,
                            focus=lambda w, v: (not v) and self._apply_settings())
        cfg.add_widget(self.sep_input)

        cfg.add_widget(Label(text="副檔名", font_size=dp(12), color=FG_DIM,
                             size_hint=(None, 1), width=dp(44)))
        self.ext_input = TextInput(
            text="", multiline=False, font_size=dp(12),
            hint_text=".mp3 .flac",
            size_hint=(1, None), height=dp(32),
            background_color=SURF, foreground_color=FG,
            cursor_color=FG,
        )
        self.ext_input.bind(on_text_validate=self._apply_settings,
                            focus=lambda w, v: (not v) and self._apply_settings())
        cfg.add_widget(self.ext_input)
        main.add_widget(cfg)

        # ── 狀態列 ──────────────────────────────────────
        self.status_lbl = Label(
            text="請點選「📁 開啟」選擇資料夾",
            font_size=dp(12), color=FG_DIM,
            size_hint_y=None, height=dp(30),
            halign="left", valign="middle",
        )
        self.status_lbl.bind(size=lambda w, s: setattr(w, "text_size", s))
        main.add_widget(self.status_lbl)

        # ── 清單區域 ────────────────────────────────────
        self.scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        self.list_layout = GridLayout(
            cols=1, size_hint_y=None, spacing=0
        )
        self.list_layout.bind(minimum_height=self.list_layout.setter("height"))
        self.scroll.add_widget(self.list_layout)
        main.add_widget(self.scroll)

        # ── 底部按鈕列 ──────────────────────────────────
        bot = ColorBox(bg_color=SURF, orientation="horizontal",
                       size_hint_y=None, height=dp(60),
                       padding=[dp(8), dp(8)], spacing=dp(8))

        sort_btn = Button(
            text="↑↓ 自然排序",
            background_normal="", background_color=SURF2,
            color=FG, font_size=dp(13),
        )
        sort_btn.bind(on_release=lambda *_: self._sort_natural())
        bot.add_widget(sort_btn)

        preview_btn = Button(
            text="🔍 預覽",
            background_normal="", background_color=SURF2,
            color=FG, font_size=dp(13),
        )
        preview_btn.bind(on_release=lambda *_: self._show_preview())
        bot.add_widget(preview_btn)

        exec_btn = Button(
            text="✅ 執行更名",
            background_normal="", background_color=ACC,
            color=WHITE, font_size=dp(14), bold=True,
        )
        exec_btn.bind(on_release=lambda *_: self._execute_rename())
        bot.add_widget(exec_btn)
        main.add_widget(bot)

        return self.root_layout

    # ════════════════════════════════════════════════════
    #  資料夾瀏覽
    # ════════════════════════════════════════════════════

    def _open_folder_browser(self):
        if IS_ANDROID:
            start = primary_external_storage_path()
        else:
            start = str(Path.home())

        popup = FolderBrowserPopup(
            start_path=start,
            on_select=self._load_folder,
        )
        popup.open()

    def _load_folder(self, folder_str: str):
        self.folder = Path(folder_str)
        self._apply_settings()

    def _apply_settings(self, *_):
        try:
            self.start_num  = int(self.start_input.text.strip()) if self.start_input.text.strip().isdigit() else 1
            self.pad_digits = max(1, int(self.pad_input.text.strip())) if self.pad_input.text.strip().isdigit() else 2
        except Exception:
            pass
        self.separator  = self.sep_input.text
        self.ext_filter = self.ext_input.text.strip()

        if self.folder:
            self._reload_files()
        else:
            self._rebuild_rows()

    def _reload_files(self):
        raw  = self.ext_filter
        exts = {(e if e.startswith(".") else f".{e}").lower()
                for e in raw.split()} if raw else set()
        try:
            files = [f for f in self.folder.iterdir()
                     if f.is_file() and (not exts or f.suffix.lower() in exts)]
        except Exception:
            files = []
        files.sort(key=lambda p: nkey(p.name))
        self.items = [FileItem(f) for f in files]
        self._rebuild_rows()
        self.status_lbl.text = f"已載入 {len(self.items)} 個檔案 — {self.folder.name}"

    # ════════════════════════════════════════════════════
    #  清單重建
    # ════════════════════════════════════════════════════

    def _rebuild_rows(self):
        self.list_layout.clear_widgets()
        self.rows = []
        for i, item in enumerate(self.items):
            row = FileRow(item=item, index=i, app_ref=self)
            self.rows.append(row)
            self.list_layout.add_widget(row)

    def _refresh_rows(self):
        """只刷新編號和預覽文字，不重建 widget。"""
        for i, row in enumerate(self.rows):
            row.refresh(i)

    # ════════════════════════════════════════════════════
    #  編號輸入 Popup
    # ════════════════════════════════════════════════════

    def open_num_input(self, row: FileRow):
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(16))
        content.add_widget(Label(
            text=f"將「{row.item.custom_name}」\n移動到第幾號位置？",
            font_size=dp(15), color=FG, halign="center",
            size_hint_y=None, height=dp(60),
        ))
        num_in = TextInput(
            text=str(self.start_num + row.index),
            multiline=False, font_size=dp(20),
            halign="center", input_filter="int",
            size_hint_y=None, height=dp(52),
            background_color=SURF2, foreground_color=FG,
            cursor_color=FG,
        )
        content.add_widget(num_in)

        btns = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        popup = Popup(title="移動到指定位置",
                      content=content,
                      size_hint=(0.85, None), height=dp(240),
                      background_color=SURF)

        cancel = Button(text="取消", background_normal="",
                        background_color=SURF2, color=FG, font_size=dp(14))
        cancel.bind(on_release=popup.dismiss)
        ok = Button(text="確認移動", background_normal="",
                    background_color=ACC, color=WHITE,
                    font_size=dp(14), bold=True)

        def _do_move(*_):
            popup.dismiss()
            try:
                target = int(num_in.text)
            except ValueError:
                return
            self._move_to(row.index, target)

        ok.bind(on_release=_do_move)
        num_in.bind(on_text_validate=_do_move)
        btns.add_widget(cancel)
        btns.add_widget(ok)
        content.add_widget(btns)
        popup.open()
        Clock.schedule_once(lambda dt: num_in.select_all(), 0.1)

    def _move_to(self, src_idx: int, target_number: int):
        dst_idx = max(0, min(target_number - self.start_num, len(self.items) - 1))
        if dst_idx == src_idx:
            return
        item = self.items.pop(src_idx)
        self.items.insert(dst_idx, item)
        self._rebuild_rows()
        self.status_lbl.text = f"已移動「{item.custom_name}」至位置 {str(self.start_num + dst_idx).zfill(self.pad_digits)}"

    # ════════════════════════════════════════════════════
    #  重新命名 Popup
    # ════════════════════════════════════════════════════

    def open_rename_popup(self, row: FileRow):
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(16))
        content.add_widget(Label(
            text=f"原始：{row.item.original_name}{row.item.suffix}",
            font_size=dp(13), color=FG_DIM, halign="left",
            size_hint_y=None, height=dp(30),
        ))
        name_in = TextInput(
            text=row.item.custom_name,
            multiline=False, font_size=dp(16),
            size_hint_y=None, height=dp(48),
            background_color=SURF2, foreground_color=FG,
            cursor_color=FG,
        )
        content.add_widget(name_in)

        btns = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        popup = Popup(title="修改檔名",
                      content=content,
                      size_hint=(0.9, None), height=dp(220),
                      background_color=SURF)

        cancel = Button(text="取消", background_normal="",
                        background_color=SURF2, color=FG, font_size=dp(14))
        cancel.bind(on_release=popup.dismiss)
        ok = Button(text="確認", background_normal="",
                    background_color=ACC, color=WHITE,
                    font_size=dp(14), bold=True)

        def _do_rename(*_):
            new = name_in.text.strip()
            if new:
                row.item.custom_name = new
            popup.dismiss()
            self._refresh_rows()

        ok.bind(on_release=_do_rename)
        name_in.bind(on_text_validate=_do_rename)
        btns.add_widget(cancel)
        btns.add_widget(ok)
        content.add_widget(btns)
        popup.open()
        Clock.schedule_once(lambda dt: name_in.select_all(), 0.1)

    # ════════════════════════════════════════════════════
    #  拖曳排序
    # ════════════════════════════════════════════════════

    def on_drag_start(self, row: FileRow, touch):
        self._drag_row = row
        self._drag_target_idx = row.index

        # 鬼影標籤（跟隨手指）
        self._ghost = Label(
            text=row.name_lbl.text,
            font_size=dp(13),
            color=(*ACC[:3], 0.85),
            size_hint=(None, None),
            size=(Window.width * 0.7, dp(48)),
            halign="left", valign="middle",
        )
        self._ghost.text_size = self._ghost.size
        self._ghost.pos = (touch.x - dp(20), touch.y - dp(24))
        self.root_layout.add_widget(self._ghost)

        # 插入線
        self._insert_line = InsertLine()
        self.root_layout.add_widget(self._insert_line)

        # 淡化被拖曳的列
        Animation(opacity=0.35, duration=0.1).start(row)

    def on_drag_move(self, row: FileRow, touch):
        if self._ghost:
            self._ghost.pos = (touch.x - dp(20), touch.y - dp(24))

        # 判斷插入位置
        target_idx = self._find_insert_index(touch.y)
        self._drag_target_idx = target_idx
        self._update_insert_line(target_idx)

    def on_drag_end(self, row: FileRow, touch):
        # 恢復透明度
        Animation(opacity=1.0, duration=0.1).start(row)

        # 移除鬼影和插入線
        if self._ghost:
            self.root_layout.remove_widget(self._ghost)
            self._ghost = None
        if self._insert_line:
            self.root_layout.remove_widget(self._insert_line)
            self._insert_line = None

        src = row.index
        dst = self._drag_target_idx
        # 調整：插入線在 dst 上方，dst > src 時需 -1
        real_dst = dst if dst <= src else dst - 1
        real_dst = max(0, min(real_dst, len(self.items) - 1))

        if real_dst != src:
            item = self.items.pop(src)
            self.items.insert(real_dst, item)
            self._rebuild_rows()
            self.status_lbl.text = f"已將「{item.custom_name}」移至位置 {str(self.start_num + real_dst).zfill(self.pad_digits)}"

        self._drag_row = None
        self._drag_target_idx = -1

    def _find_insert_index(self, touch_y: float) -> int:
        """根據手指 y 座標找出插入位置（0 = 最上方）。"""
        for i, row in enumerate(self.rows):
            row_mid = row.y + row.height / 2
            if touch_y > row_mid:
                return i
        return len(self.rows)

    def _update_insert_line(self, idx: int):
        if not self._insert_line:
            return
        if idx < len(self.rows):
            ref_row = self.rows[idx]
            line_y  = ref_row.top   # 插在該列上方
        elif self.rows:
            line_y  = self.rows[-1].y  # 插在最後一列下方
        else:
            return
        # 轉換為 root_layout 座標
        self._insert_line.pos  = (0, line_y)
        self._insert_line.size = (Window.width, dp(2))

    # ════════════════════════════════════════════════════
    #  排序 & 預覽 & 執行
    # ════════════════════════════════════════════════════

    def _sort_natural(self):
        self.items.sort(key=lambda i: nkey(i.original_name + i.suffix))
        self._rebuild_rows()

    def _show_preview(self):
        if not self.items:
            self._alert("提示", "尚未載入任何檔案。"); return

        content = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4))
        scroll  = ScrollView(size_hint=(1, 1))
        grid    = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        grid.bind(minimum_height=grid.setter("height"))

        for i, item in enumerate(self.items):
            num   = str(self.start_num + i).zfill(self.pad_digits)
            after = f"{num}{self.separator}{item.final_name}"
            bg    = ROW_ODD if i % 2 else ROW_EVEN
            row   = ColorBox(bg_color=bg, orientation="horizontal",
                             size_hint_y=None, height=dp(44), padding=[dp(8), 0])
            row.add_widget(Label(
                text=after, font_size=dp(12), color=FG,
                halign="left", valign="middle", shorten=True,
            ))
            grid.add_widget(row)

        scroll.add_widget(grid)
        content.add_widget(scroll)

        close_btn = Button(
            text="關閉", size_hint_y=None, height=dp(48),
            background_normal="", background_color=SURF2, color=FG,
        )
        popup = Popup(title="📋 更名預覽",
                      content=content,
                      size_hint=(0.95, 0.88),
                      background_color=SURF)
        close_btn.bind(on_release=popup.dismiss)
        content.add_widget(close_btn)
        popup.open()

    def _execute_rename(self):
        if not self.items:
            self._alert("提示", "尚未載入任何檔案。"); return

        self._confirm(
            "確認執行",
            f"即將對 {len(self.items)} 個檔案更名。\n此操作無法自動復原，確定繼續？",
            self._do_rename,
        )

    def _do_rename(self):
        ok = skip = fail = 0
        errors = []
        for i, item in enumerate(self.items):
            num      = str(self.start_num + i).zfill(self.pad_digits)
            new_name = f"{num}{self.separator}{item.final_name}"
            new_path = item.path.parent / new_name
            if item.path.name == new_name:
                skip += 1; continue
            if new_path.exists():
                errors.append(f"衝突：{new_name}"); skip += 1; continue
            try:
                item.path.rename(new_path)
                item.path = new_path
                ok += 1
            except OSError as e:
                errors.append(str(e)); fail += 1

        self._rebuild_rows()
        msg = f"成功：{ok}　跳過：{skip}　失敗：{fail}"
        if errors:
            msg += "\n\n" + "\n".join(errors[:5])
        self._alert("執行結果", msg)
        self.status_lbl.text = f"更名完成：成功 {ok}，跳過 {skip}，失敗 {fail}"

    # ════════════════════════════════════════════════════
    #  通用 Popup 工具
    # ════════════════════════════════════════════════════

    def _alert(self, title: str, msg: str):
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12))
        content.add_widget(Label(text=msg, font_size=dp(14), color=FG,
                                 halign="center", valign="middle"))
        btn = Button(text="確定", size_hint_y=None, height=dp(48),
                     background_normal="", background_color=ACC,
                     color=WHITE, font_size=dp(14))
        popup = Popup(title=title, content=content,
                      size_hint=(0.85, None), height=dp(200),
                      background_color=SURF)
        btn.bind(on_release=popup.dismiss)
        content.add_widget(btn)
        popup.open()

    def _confirm(self, title: str, msg: str, on_ok):
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12))
        content.add_widget(Label(text=msg, font_size=dp(14), color=FG,
                                 halign="center", valign="middle"))
        btns = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        popup = Popup(title=title, content=content,
                      size_hint=(0.88, None), height=dp(220),
                      background_color=SURF)

        cancel = Button(text="取消", background_normal="",
                        background_color=SURF2, color=FG, font_size=dp(14))
        cancel.bind(on_release=popup.dismiss)
        ok = Button(text="確定", background_normal="",
                    background_color=ACC, color=WHITE,
                    font_size=dp(14), bold=True)

        def _go(*_):
            popup.dismiss()
            on_ok()

        ok.bind(on_release=_go)
        btns.add_widget(cancel)
        btns.add_widget(ok)
        content.add_widget(btns)
        popup.open()


if __name__ == "__main__":
    RenameApp().run()
