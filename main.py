#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KivyMD YouTube Downloader – Fixed & Working (Nov 2025)
"""

import os
import re
import threading
import datetime

from kivy.lang import Builder
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty, ListProperty
from kivy.storage.jsonstore import JsonStore

from kivymd.app import MDApp
from kivymd.uix.filemanager import MDFileManager
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import OneLineListItem

import yt_dlp


# ----------------------------------------------------------------------
# KV (UI)
# ----------------------------------------------------------------------
KV = """
BoxLayout:
    orientation: "vertical"
    padding: dp(12)
    spacing: dp(10)

    MDCard:
        size_hint_y: None
        height: dp(180)
        elevation: 6
        padding: dp(12)
        radius: [dp(12)]

        BoxLayout:
            orientation: "vertical"
            spacing: dp(8)

            MDTextField:
                id: url_field
                hint_text: "YouTube URL"
                required: True

            BoxLayout:
                size_hint_y: None
                height: dp(40)
                spacing: dp(8)

                MDLabel:
                    text: "Folder:"
                    size_hint_x: None
                    width: dp(60)

                MDLabel:
                    id: folder_label
                    text: app.download_folder or "No folder selected"
                    theme_text_color: "Secondary"
                    shorten: True

                MDFillRoundFlatIconButton:
                    text: "Choose"
                    icon: "folder"
                    size_hint_x: None
                    width: dp(120)
                    on_release: app.open_file_manager()

            BoxLayout:
                size_hint_y: None
                height: dp(48)
                spacing: dp(8)

                MDRaisedButton:
                    text: "Download"
                    on_release: app.start_download()
                MDFlatButton:
                    text: "Clear"
                    on_release: app.clear_inputs()

    MDProgressBar:
        id: progress
        value: app.progress

    MDCard:
        size_hint_y: None
        height: dp(180)
        elevation: 4
        padding: dp(8)

        BoxLayout:
            orientation: "vertical"
            spacing: dp(6)

            MDLabel:
                text: "Status"
                font_style: "Subtitle1"

            MDLabel:
                id: status_label
                text: app.status_text
                theme_text_color: "Secondary"

    MDCard:
        size_hint_y: None
        height: dp(180)
        elevation: 4
        padding: dp(8)

        BoxLayout:
            orientation: "vertical"

            MDLabel:
                text: "Recent Downloads"
                font_style: "Subtitle1"

            ScrollView:
                MDList:
                    id: recent_list
"""


# ----------------------------------------------------------------------
# Helper – Shorts → watch?v
# ----------------------------------------------------------------------
def fix_shorts_url(url: str) -> str:
    m = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------
class YouTubeDownloaderApp(MDApp):
    status_text = StringProperty("Ready")
    progress = NumericProperty(0)
    download_folder = StringProperty("")
    recent = ListProperty([])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.file_manager = None
        self.store = JsonStore("ytdl_store.json")
        if self.store.exists("recent"):
            self.recent = self.store.get("recent")["items"]

    # ------------------------------------------------------------------
    def build(self):
        self.theme_cls.primary_palette = "Red"
        self.theme_cls.theme_style = "Light"
        self.root = Builder.load_string(KV)          # ← root is now set
        Clock.schedule_once(self._post_build, 0)
        return self.root

    def _post_build(self, dt):
        self._populate_recent()

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _populate_recent(self):
        if not self.root or 'recent_list' not in self.root.ids:
            return
        lst = self.root.ids.recent_list
        lst.clear_widgets()
        for item in reversed(self.recent[-10:]):
            lst.add_widget(OneLineListItem(text=f"{item['title']} — {item['time']}"))

    def open_file_manager(self):
        if not self.file_manager:
            self.file_manager = MDFileManager(
                exit_manager=self._close_file_manager,
                select_path=self._select_path,
                preview=False,
            )
        self.file_manager.show(os.path.expanduser("~"))

    def _close_file_manager(self, *args):
        if self.file_manager:
            self.file_manager.close()

    def _select_path(self, path):
        self.download_folder = path
        self.root.ids.folder_label.text = path
        self._close_file_manager()

    def clear_inputs(self):
        self.root.ids.url_field.text = ""
        self.progress = 0
        self.status_text = "Ready"

    # ------------------------------------------------------------------
    # Download logic
    # ------------------------------------------------------------------
    def start_download(self):
        url = self.root.ids.url_field.text.strip()
        if not url:
            return self._show_dialog("Please paste a YouTube URL.")
        if not self.download_folder:
            return self._show_dialog("Please choose a folder.")
        threading.Thread(target=self._download_thread, args=(url,), daemon=True).start()

    def _download_thread(self, raw_url: str):
        self.progress = 0
        self._set_status("Preparing…")

        url = fix_shorts_url(raw_url)

        # ------------------------------------------------------------------
        # *** THE FIX ***
        # outtmpl must be a *directory* + template, NOT just a template string
        # ------------------------------------------------------------------
        outtmpl = os.path.join(self.download_folder, "%(title)s.%(ext)s")

        ydl_opts = {
            "format": "best[ext=mp4]/best",           # highest MP4
            "outtmpl": outtmpl,                       # ← fixed path
            "noplaylist": True,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            # 2025 anti-block tricks
            "player_client": "android",
            "extractor_args": {"youtube": {"skip": ["dash"]}},
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "video")
                self._set_status(f"Downloading: {title}")
                ydl.download([url])

            self._set_status("Download finished")
            self._record_recent(title)
            self.progress = 100

        except Exception as e:
            self._set_status(f"Error: {e}")

    # ------------------------------------------------------------------
    # Progress hook
    # ------------------------------------------------------------------
    def _progress_hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            downloaded = d.get("downloaded_bytes") or 0
            percent = int(downloaded / total * 100)
            Clock.schedule_once(lambda dt: self._update_progress(percent))
        elif d["status"] == "finished":
            Clock.schedule_once(lambda dt: self._update_progress(100))

    @mainthread
    def _update_progress(self, val: int):
        self.progress = val

    @mainthread
    def _set_status(self, txt: str):
        self.status_text = txt

    # ------------------------------------------------------------------
    # Recent list
    # ------------------------------------------------------------------
    def _record_recent(self, title: str):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.recent.append({"title": title, "time": now})
        self.store.put("recent", items=self.recent)
        Clock.schedule_once(lambda _: self._populate_recent())

    # ------------------------------------------------------------------
    # Dialog
    # ------------------------------------------------------------------
    def _show_dialog(self, txt: str):
        MDDialog(title="Notice", text=txt, size_hint=(0.8, None)).open()


# ----------------------------------------------------------------------
if __name__ == "__main__":
    YouTubeDownloaderApp().run()
