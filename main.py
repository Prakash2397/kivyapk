#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KivyMD YouTube Downloader – Fixed & Stable – Nov 2025
• Works on Android (SAF + default Downloads) + Desktop
• Fixed crash on "Load Formats"
• Clean quality selector (highest first)
"""
import os
import re
import threading
import datetime
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
from kivymd.uix.menu import MDDropdownMenu
import yt_dlp

KV = '''
BoxLayout:
    orientation: "vertical"
    padding: dp(12)
    spacing: dp(10)

    MDCard:
        size_hint_y: None
        height: dp(230)
        elevation: 6
        padding: dp(12)
        radius: [dp(12)]

        BoxLayout:
            orientation: "vertical"
            spacing: dp(8)

            MDTextField:
                id: url_field
                hint_text: "Paste YouTube URL here"
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
                    shorten_from: "right"
                MDFillRoundFlatIconButton:
                    text: "Choose"
                    icon: "folder-outline"
                    size_hint_x: None
                    width: dp(120)
                    on_release: app.open_file_manager()

            BoxLayout:
                size_hint_y: None
                height: dp(48)
                spacing: dp(8)
                MDRaisedButton:
                    text: "Load Formats"
                    on_release: app.load_formats()
                MDFlatButton:
                    id: quality_btn
                    text: "Quality"
                    disabled: True
                    on_release: app.quality_menu.open() if app.quality_menu else None
                MDRaisedButton:
                    text: "Download"
                    on_release: app.start_download()
                MDFlatButton:
                    text: "Clear"
                    on_release: app.clear_inputs()

    MDCard:
        size_hint_y: None
        height: dp(60)
        elevation: 4
        padding: dp(8)
        MDBoxLayout:
            orientation: "horizontal"
            adaptive_height: True
            spacing: dp(8)
            MDProgressBar:
                id: progress
                value: app.progress
                size_hint_x: 0.8
            MDLabel:
                id: percent_label
                text: f"{int(app.progress)} %"
                halign: "center"
                size_hint_x: 0.2

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
'''

def fix_shorts_url(url: str) -> str:
    m = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


class AndroidSAF:
    def __init__(self, uri_str: str):
        from jnius import autoclass
        self.Uri = autoclass('android.net.Uri')
        self.DocumentsContract = autoclass('android.provider.DocumentsContract')
        self.ContentResolver = autoclass('android.content.ContentResolver')
        self.PythonActivity = autoclass('org.kivy.android.PythonActivity')
        self.uri = self.Uri.parse(uri_str)
        self.cr = self.PythonActivity.mActivity.getContentResolver()

    def create_file(self, display_name: str, mime: str = "video/mp4"):
        try:
            return self.DocumentsContract.createDocument(self.cr, self.uri, mime, display_name)
        except:
            return None

    def open_output_stream(self, file_uri):
        return self.cr.openOutputStream(file_uri)


class YouTubeDownloaderApp(MDApp):
    status_text = StringProperty("Ready")
    progress = NumericProperty(0)
    download_folder = StringProperty("")
    recent = ListProperty([])
    _saf = None
    _folder_uri = None
    _default_path = None
    _formats = []
    _selected_format = None
    quality_menu = None
    DEFAULT_FOLDER_NAME = "YouTube Downloads"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.file_manager = None
        self.store = JsonStore("ytdl_store.json")

        if self.store.exists("recent"):
            self.recent = self.store.get("recent")["items"]

        if self.store.exists("folder_uri"):
            data = self.store.get("folder_uri")
            self._folder_uri = data["uri"]
            self.download_folder = data["name"]

        if platform == 'android':
            self._setup_android_default()
            if self._folder_uri:
                self._saf = AndroidSAF(self._folder_uri)
        else:
            self._setup_desktop_default()

    def _setup_android_default(self):
        base = "/storage/emulated/0/Download"
        self._default_path = os.path.join(base, self.DEFAULT_FOLDER_NAME)
        os.makedirs(self._default_path, exist_ok=True)
        if not self.download_folder:
            self.download_folder = self._default_path

    def _setup_desktop_default(self):
        default_path = os.path.join(os.path.expanduser("~"), self.DEFAULT_FOLDER_NAME)
        os.makedirs(default_path, exist_ok=True)
        if not self.download_folder:
            self.download_folder = default_path

    def build(self):
        self.theme_cls.primary_palette = "Red"
        self.theme_cls.theme_style = "Light"
        self.root = Builder.load_string(KV)
        Clock.schedule_once(self._post_build, 0)
        return self.root

    def _post_build(self, dt):
        self.root.ids.folder_label.text = self.download_folder
        self._populate_recent()

    def _populate_recent(self):
        lst = self.root.ids.recent_list
        lst.clear_widgets()
        for item in reversed(self.recent[-10:]):
            lst.add_widget(OneLineListItem(text=f"{item['title']} — {item['time']}"))

    def open_file_manager(self):
        if platform == 'android':
            self._android_folder_picker()
        else:
            self._desktop_file_manager()

    def _android_folder_picker(self):
        try:
            from jnius import autoclass
            from android.runnable import run_on_ui_thread
            Intent = autoclass('android.content.Intent')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')

            @run_on_ui_thread
            def start_picker():
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                intent.addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION |
                                Intent.FLAG_GRANT_READ_URI_PERMISSION |
                                Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                PythonActivity.mActivity.startActivityForResult(intent, 1001)

            start_picker()

            if not hasattr(PythonActivity.mActivity, 'ytdl_listener_set'):
                PythonActivity.mActivity.ytdl_listener_set = True
                def on_activity_result(request_code, result_code, data):
                    if request_code == 1001:
                        self.on_activity_result(request_code, result_code, data)
                PythonActivity.mActivity.setResultListener(on_activity_result)
        except Exception as e:
            self._show_dialog(f"Picker error: {e}")

    def on_activity_result(self, request_code, result_code, intent):
        if request_code != 1001 or result_code != -1 or not intent:
            return
        try:
            from jnius import autoclass
            Uri = autoclass('android.net.Uri')
            DocumentFile = autoclass('android.provider.DocumentsContract$DocumentFile')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')

            uri = intent.getData()
            cr = PythonActivity.mActivity.getContentResolver()
            cr.takePersistableUriPermission(uri, 3)  # READ|WRITE

            doc = DocumentFile.fromTreeUri(PythonActivity.mActivity, uri)
            name = doc.getName() or "Selected Folder"

            self._folder_uri = uri.toString()
            self.store.put("folder_uri", uri=self._folder_uri, name=name)
            self.download_folder = name
            self.root.ids.folder_label.text = name
            self._saf = AndroidSAF(self._folder_uri)
            self._show_dialog(f"Folder set: {name}")
        except Exception as e:
            self._show_dialog(f"Error: {e}")

    def _desktop_file_manager(self):
        if not self.file_manager:
            self.file_manager = MDFileManager(
                exit_manager=lambda x: self.file_manager.close(),
                select_path=self._select_desktop_path,
                preview=False,
            )
        self.file_manager.show(os.path.expanduser("~"))

    def _select_desktop_path(self, path):
        self.download_folder = path
        self.root.ids.folder_label.text = path
        self.file_manager.close()

    def clear_inputs(self):
        self.root.ids.url_field.text = ""
        self.progress = 0
        self.status_text = "Ready"
        self._reset_quality_selector()

    # ==================== QUALITY SELECTOR (FIXED) ====================
    def load_formats(self):
        url = self.root.ids.url_field.text.strip()
        if not url:
            return self._show_dialog("Enter YouTube URL first")
        self._set_status("Loading formats...")
        threading.Thread(target=self._load_formats_thread, args=(url,), daemon=True).start()

    def _load_formats_thread(self, raw_url):
        url = fix_shorts_url(raw_url)
        try:
            ydl = yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True})
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])

            self._formats = []
            seen = set()

            for f in formats:
                if f.get('vcodec') == 'none' or f.get('acodec') == 'none' and f.get('height') is None:
                    continue
                height = f.get('height')
                if not height:
                    continue
                ext = f.get('ext', 'mp4')
                fps = f.get('fps')
                fps_str = f" ({fps}fps)" if fps and fps > 30 else ""
                label = f"{height}p{fps_str} • {ext.upper()}"
                if label in seen:
                    continue
                seen.add(label)
                self._formats.append({
                    "format_id": f["format_id"],
                    "text": label,
                    "height": height
                })

            # Sort by height descending
            self._formats.sort(key=lambda x: x["height"], reverse=True)

            Clock.schedule_once(self._build_quality_menu)
        except Exception as e:
            Clock.schedule_once(lambda dt: self._show_dialog(f"Error: {e}"))

    @mainthread
    def _build_quality_menu(self, dt):
        if not self._formats:
            self._show_dialog("No video formats found")
            self._set_status("Ready")
            return

        menu_items = [{
            "text": f["text"],
            "viewclass": "OneLineListItem",
            "on_release": lambda x=f["format_id"], y=f["text"]: self._select_quality(x, y),
        } for f in self._formats]

        self.quality_menu = MDDropdownMenu(
            caller=self.root.ids.quality_btn,
            items=menu_items,
            width_mult=4,
        )
        self.root.ids.quality_btn.disabled = False
        self.root.ids.quality_btn.text = f"{len(self._formats)} qualities"
        self._set_status("Select quality ↓")
        self.quality_menu.open()

    def _select_quality(self, fmt_id, text):
        self._selected_format = fmt_id
        self.root.ids.quality_btn.text = text.split(" • ")[0]  # Show only "1080p"
        self.quality_menu.dismiss()

    def _reset_quality_selector(self):
        self.root.ids.quality_btn.text = "Quality"
        self.root.ids.quality_btn.disabled = True
        self._selected_format = None
        self._formats = []
        if self.quality_menu:
            self.quality_menu.dismiss()
            self.quality_menu = None

    # ==================== DOWNLOAD ====================
    def start_download(self):
        url = self.root.ids.url_field.text.strip()
        if not url or not self._selected_format:
            return self._show_dialog("URL and quality required")
        threading.Thread(target=self._download_thread, args=(url,), daemon=True).start()

    def _download_thread(self, raw_url):
        self.progress = 0
        self._set_status("Preparing...")
        url = fix_shorts_url(raw_url)

        ydl_opts = {
            'format': self._selected_format,
            'noplaylist': True,
            'progress_hooks': [self._progress_hook],
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
        }

        if platform == 'android' and self._saf:
            # SAF download
            info = yt_dlp.YoutubeDL({'quiet': True}).extract_info(url, download=False)
            title = info.get('title', 'video')
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', title)
            filename = f"{safe_name}.mp4"

            file_uri = self._saf.create_file(filename)
            if not file_uri:
                self._set_status("Failed to create file")
                return

            tmp_opts = ydl_opts.copy()
            tmp_opts['outtmpl'] = '/data/data/org.test.ytdl/cache_%(id)s.%(ext)s'

            def saf_hook(d):
                if d['status'] == 'finished':
                    tmp_path = d['filename']
                    with open(tmp_path, 'rb') as src:
                        with self._saf.open_output_stream(file_uri) as dst:
                            while True:
                                chunk = src.read(1024*1024)
                                if not chunk:
                                    break
                                dst.write(chunk)
                    os.unlink(tmp_path)
                self._progress_hook(d)

            tmp_opts['progress_hooks'] = [saf_hook]
            self._set_status(f"Downloading: {title}")

            with yt_dlp.YoutubeDL(tmp_opts) as ydl:
                ydl.download([url])

        else:
            # Normal download
            folder = self._default_path if platform == 'android' else self.download_folder
            ydl_opts['outtmpl'] = os.path.join(folder, '%(title)s.%(ext)s')
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.download([url])
                title = info.get('title', 'Unknown')
                self._record_recent(title)

        self._set_status("Download finished!")
        self.progress = 100

    @mainthread
    def _progress_hook(self, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
            downloaded = d.get('downloaded_bytes', 0)
            percent = int(downloaded / total * 100)
            self.progress = percent
            self.root.ids.percent_label.text = f"{percent} %"
        elif d['status'] == 'finished':
            self.progress = 100
            self.root.ids.percent_label.text = "100 %"

    @mainthread
    def _set_status(self, txt):
        self.status_text = txt

    def _record_recent(self, title):
        now = datetime.datetime.now().strftime("%b %d, %H:%M")
        item = {"title": title[:50] + "..." if len(title) > 50 else title, "time": now}
        self.recent.append(item)
        self.store.put("recent", items=self.recent)
        Clock.schedule_once(lambda dt: self._populate_recent())

    def _show_dialog(self, text):
        MDDialog(title="Notice", text=text, size_hint=(0.8, None), auto_dismiss=True).open()


if __name__ == '__main__':
    YouTubeDownloaderApp().run()
