#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KivyMD YouTube Downloader — saves to public Downloads/YouTubeDownloads
Requires: kivy, kivymd, yt-dlp. On Android pyjnius available via build.
"""

import os
import re
import threading
import datetime
import tempfile
from kivy.lang import Builder
from kivy.clock import Clock, mainthread
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty, ListProperty
from kivy.storage.jsonstore import JsonStore
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.filemanager import MDFileManager
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import OneLineListItem
import yt_dlp

KV = '''
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
                # No manual choose — Option A uses public Downloads path automatically
                MDLabel:
                    text: ""
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
        height: dp(120)
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
        height: dp(160)
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
'''

# ---------------- Helper: shorts -> watch?v ----------------
def fix_shorts_url(url: str) -> str:
    m = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url

# ---------------- Android: save file into public Downloads using MediaStore --------------
def save_file_to_downloads_android(src_path: str, display_name: str, mime_type: str = "video/mp4"):
    """
    Insert file into MediaStore Downloads and copy bytes from src_path.
    Returns True on success, raises on failure.
    """
    from jnius import autoclass, cast
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    ContentValues = autoclass('android.content.ContentValues')
    MediaStore = autoclass('android.provider.MediaStore')
    Uri = autoclass('android.net.Uri')

    activity = PythonActivity.mActivity
    resolver = activity.getContentResolver()

    values = ContentValues()
    values.put(MediaStore.MediaColumns.DISPLAY_NAME, display_name)
    values.put(MediaStore.MediaColumns.MIME_TYPE, mime_type)
    # Put relative path to Downloads/YouTubeDownloads (Android 10+)
    values.put(MediaStore.MediaColumns.RELATIVE_PATH, "Download/YouTubeDownloads")

    downloads_uri = MediaStore.Downloads.EXTERNAL_CONTENT_URI
    new_uri = resolver.insert(downloads_uri, values)
    if new_uri is None:
        raise RuntimeError("Failed to create MediaStore entry")

    out_stream = resolver.openOutputStream(new_uri)
    if out_stream is None:
        raise RuntimeError("Failed to open output stream for MediaStore entry")

    try:
        with open(src_path, "rb") as f:
            buf = f.read(65536)
            while buf:
                out_stream.write(buf)
                buf = f.read(65536)
    finally:
        out_stream.close()

    return True

# ---------------- Desktop: ensure public Downloads/YouTubeDownloads path --------------
def get_desktop_downloads_path(folder_name="YouTubeDownloads"):
    base = os.path.join(os.path.expanduser("~"), "Downloads")
    path = os.path.join(base, folder_name)
    os.makedirs(path, exist_ok=True)
    return path

# ---------------- App ----------------
class YouTubeDownloaderApp(MDApp):
    status_text = StringProperty("Ready")
    progress = NumericProperty(0)
    download_folder = StringProperty("")   # display text
    recent = ListProperty([])

    DEFAULT_FOLDER_NAME = "YouTubeDownloads"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.store = JsonStore("ytdl_store.json")
        if self.store.exists("recent"):
            self.recent = self.store.get("recent")["items"]

        # Set platform-specific download folder display name
        if platform == "android":
            # public Downloads/YouTubeDownloads (display to user)
            self.download_folder = os.path.join("Downloads", self.DEFAULT_FOLDER_NAME)
        else:
            self.download_folder = get_desktop_downloads_path(self.DEFAULT_FOLDER_NAME)

    def build(self):
        self.theme_cls.primary_palette = "Red"
        self.theme_cls.theme_style = "Light"
        self.root = Builder.load_string(KV)
        Clock.schedule_once(self._post_build, 0)
        return self.root

    def _post_build(self, dt):
        self._populate_recent()
        if self.root:
            self.root.ids.folder_label.text = self.download_folder

    def _populate_recent(self):
        if not self.root:
            return
        lst = self.root.ids.recent_list
        lst.clear_widgets()
        for item in reversed(self.recent[-10:]):
            lst.add_widget(OneLineListItem(text=f"{item['title']} — {item['time']}"))

    def clear_inputs(self):
        self.root.ids.url_field.text = ""
        self.progress = 0
        self.status_text = "Ready"

    def start_download(self):
        url = self.root.ids.url_field.text.strip()
        if not url:
            self._show_dialog("Please paste a YouTube URL")
            return
        threading.Thread(target=self._download_thread, args=(url,), daemon=True).start()

    def _download_thread(self, raw_url: str):
        self.progress = 0
        self._set_status("Preparing…")
        url = fix_shorts_url(raw_url)

        # yt-dlp options: download to temporary file, then copy to public downloads via MediaStore (Android)
        tmpdir = tempfile.gettempdir()
        tmp_out = os.path.join(tmpdir, "%(title)s.%(ext)s")

        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "outtmpl": tmp_out,
            # recommended modern options
            "player_client": "android",
        }

        try:
            with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "video")
                ext = info.get("ext", "mp4")
        except Exception as e:
            self._set_status(f"Error extracting info: {e}")
            return

        safe_name = "".join(c if c not in r'\/:*?"<>|' else "_" for c in title)
        temp_filename_template = os.path.join(tmpdir, safe_name + ".%(ext)s")
        ydl_opts["outtmpl"] = temp_filename_template

        # run download
        try:
            self._set_status(f"Downloading: {title}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            self._set_status(f"Download error: {e}")
            return

        # locate downloaded temp file
        tmp_file = temp_filename_template.replace("%(ext)s", ext)
        if not os.path.exists(tmp_file):
            self._set_status("Downloaded file not found")
            return

        # copy/move file to public downloads
        final_display_name = f"{safe_name}.{ext}"

        if platform == "android":
            # use MediaStore to insert into Downloads/YouTubeDownloads
            try:
                save_file_to_downloads_android(tmp_file, final_display_name, mime_type="video/mp4")
                os.remove(tmp_file)
            except Exception as e:
                # fallback: try direct write to /storage/emulated/0/Download/YouTubeDownloads/ if allowed
                try:
                    downloads_root = os.path.join("/storage/emulated/0", "Download", self.DEFAULT_FOLDER_NAME)
                    os.makedirs(downloads_root, exist_ok=True)
                    dest = os.path.join(downloads_root, final_display_name)
                    with open(tmp_file, "rb") as src, open(dest, "wb") as dst:
                        while True:
                            chunk = src.read(65536)
                            if not chunk:
                                break
                            dst.write(chunk)
                    os.remove(tmp_file)
                except Exception as e2:
                    self._set_status(f"Save failed: {e} ; {e2}")
                    return
        else:
            # Desktop: move to ~/Downloads/YouTubeDownloads
            try:
                dest_dir = get_desktop_downloads_path(self.DEFAULT_FOLDER_NAME)
                dest_path = os.path.join(dest_dir, final_display_name)
                os.replace(tmp_file, dest_path)
            except Exception as e:
                self._set_status(f"Save failed: {e}")
                return

        self._set_status("Download finished")
        self._record_recent(title)
        self.progress = 100

    # progress hook from yt-dlp runs in download thread
    def _progress_hook(self, d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            downloaded = d.get("downloaded_bytes") or 0
            percent = int(downloaded / total * 100)
            Clock.schedule_once(lambda dt: self._update_progress(percent))
        elif status == "finished":
            Clock.schedule_once(lambda dt: self._update_progress(100))

    @mainthread
    def _update_progress(self, val: int):
        self.progress = val

    @mainthread
    def _set_status(self, txt: str):
        self.status_text = txt

    def _record_recent(self, title: str):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.recent.append({"title": title, "time": now})
        self.store.put("recent", items=self.recent)
        Clock.schedule_once(lambda dt: self._populate_recent())

    def _show_dialog(self, txt: str):
        MDDialog(title="Notice", text=txt, size_hint=(0.8, None)).open()

# ---------------- run ----------------
if __name__ == "__main__":
    YouTubeDownloaderApp().run()
