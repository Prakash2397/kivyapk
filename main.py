#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KivyMD YouTube Downloader – Android (internal shared storage) + Desktop – Nov 2025
Features:
 • Default folder: /storage/emulated/0/Download/YouTube Downloads
 • Full path shown in label
 • Multi‑quality selector (dropdown) – **FIXED**
 • Progress bar with percentage text
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

# ----------------------------------------------------------------------
# KV (UI)
# ----------------------------------------------------------------------
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
                    shorten_from: "right"

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

# ----------------------------------------------------------------------
# Helper – Shorts → watch?v
# ----------------------------------------------------------------------
def fix_shorts_url(url: str) -> str:
    m = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url

# ----------------------------------------------------------------------
# Android SAF helper
# ----------------------------------------------------------------------
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
        return self.DocumentsContract.createDocument(self.cr, self.uri, mime, display_name)

    def open_output_stream(self, file_uri):
        return self.cr.openOutputStream(file_uri)

# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------
class YouTubeDownloaderApp(MDApp):
    status_text = StringProperty("Ready")
    progress = NumericProperty(0)
    download_folder = StringProperty("")   # full path shown in UI
    recent = ListProperty([])

    # Android only
    _saf = None
    _folder_uri = None
    _default_path = None

    # Quality selector
    _formats = []          # list of dicts: {"format_id":..., "text":...}
    _selected_format = None
    quality_menu = None    # <-- will be created once after formats are loaded

    DEFAULT_FOLDER_NAME = "YouTube Downloads"

    # ------------------------------------------------------------------
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.file_manager = None
        self.store = JsonStore("ytdl_store.json")

        # recent list
        if self.store.exists("recent"):
            self.recent = self.store.get("recent")["items"]

        # persisted SAF folder
        if self.store.exists("folder_uri"):
            self._folder_uri = self.store.get("folder_uri")["uri"]
            self.download_folder = self.store.get("folder_uri")["name"]

        # platform specific defaults
        if platform == 'android':
            self._setup_android_default()
            if self._folder_uri:
                self._saf = AndroidSAF(self._folder_uri)
        else:
            self._setup_desktop_default()

    # ------------------------------------------------------------------
    # Android – default internal shared storage folder
    # ------------------------------------------------------------------
    def _setup_android_default(self):
        base = "/storage/emulated/0/Download"
        self._default_path = os.path.join(base, self.DEFAULT_FOLDER_NAME)
        os.makedirs(self._default_path, exist_ok=True)
        self.download_folder = self._default_path

    # ------------------------------------------------------------------
    # Desktop – ~/YouTube Downloads
    # ------------------------------------------------------------------
    def _setup_desktop_default(self):
        default_path = os.path.join(os.path.expanduser("~"), self.DEFAULT_FOLDER_NAME)
        os.makedirs(default_path, exist_ok=True)
        self.download_folder = default_path

    # ------------------------------------------------------------------
    def build(self):
        self.theme_cls.primary_palette = "Red"
        self.theme_cls.theme_style = "Light"
        self.root = Builder.load_string(KV)
        Clock.schedule_once(self._post_build, 0)
        return self.root

    def _post_build(self, dt):
        self._populate_recent()
        self.root.ids.folder_label.text = self.download_folder

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _populate_recent(self):
        lst = self.root.ids.recent_list
        lst.clear_widgets()
        for item in reversed(self.recent[-10:]):
            lst.add_widget(OneLineListItem(text=f"{item['title']} — {item['time']}"))

    # ------------------------------------------------------------------
    # Folder picker
    # ------------------------------------------------------------------
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
            app = self

            @run_on_ui_thread
            def start_picker():
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                intent.addFlags(
                    Intent.FLAG_GRANT_READ_URI_PERMISSION |
                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION |
                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                )
                activity = PythonActivity.mActivity
                activity.startActivityForResult(intent, 1001)
                if not hasattr(activity, 'ytdl_result_listener_set'):
                    activity.ytdl_result_listener_set = True
                    def result_handler(req_code, res_code, data):
                        if req_code == 1001:
                            app.on_activity_result(req_code, res_code, data)
                    activity.setResultListener(result_handler)
            start_picker()
        except Exception as e:
            self._show_dialog(f"Error opening picker: {e}")

    def on_activity_result(self, request_code, result_code, intent):
        if request_code != 1001 or result_code != -1:
            self._show_dialog("Folder selection cancelled.")
            return
        try:
            from jnius import autoclass
            Uri = autoclass('android.net.Uri')
            DocumentFile = autoclass('android.provider.DocumentsContract$DocumentFile')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            uri = intent.getData()
            cr = PythonActivity.mActivity.getContentResolver()
            cr.takePersistableUriPermission(
                uri,
                autoclass('android.content.Intent').FLAG_GRANT_READ_URI_PERMISSION |
                autoclass('android.content.Intent').FLAG_GRANT_WRITE_URI_PERMISSION
            )
            doc_file = DocumentFile.fromTreeUri(PythonActivity.mActivity, uri)
            name = doc_file.getName() or "Selected Folder"
            self._folder_uri = uri.toString()
            self.store.put("folder_uri", uri=self._folder_uri, name=name)
            self.download_folder = name
            self.root.ids.folder_label.text = name
            self._saf = AndroidSAF(self._folder_uri)
            self._show_dialog(f"Folder selected: {name}")
        except Exception as e:
            self._show_dialog(f"Error: {str(e)}")

    def _desktop_file_manager(self):
        if not self.file_manager:
            self.file_manager = MDFileManager(
                exit_manager=self._close_file_manager,
                select_path=self._select_desktop_path,
                preview=False,
            )
        self.file_manager.show(os.path.expanduser("~"))

    def _close_file_manager(self, *args):
        if self.file_manager:
            self.file_manager.close()

    def _select_desktop_path(self, path):
        self.download_folder = path
        self.root.ids.folder_label.text = path
        self._close_file_manager()

    # ------------------------------------------------------------------
    def clear_inputs(self):
        self.root.ids.url_field.text = ""
        self.progress = 0
        self.status_text = "Ready"
        self._reset_quality_selector()

    # ------------------------------------------------------------------
    # ---------- MULTI‑QUALITY ----------
    # ------------------------------------------------------------------
    def load_formats(self):
        url = self.root.ids.url_field.text.strip()
        if not url:
            self._show_dialog("Enter a YouTube URL first.")
            return
        self._set_status("Loading formats…")
        threading.Thread(target=self._load_formats_thread, args=(url,), daemon=True).start()

    def _load_formats_thread(self, raw_url: str):
        url = fix_shorts_url(raw_url)
        try:
            ydl = yt_dlp.YoutubeDL({"quiet": True})
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])

            self._formats = []
            for f in formats:
                if f.get("vcodec") == "none":      # skip audio‑only
                    continue
                height = f.get("height") or 0
                ext = f.get("ext", "")
                codec = f.get("vcodec", "").split(".")[0]
                label = f"{height}p – {codec} – {ext}"
                self._formats.append({"format_id": f["format_id"], "text": label})

            # Sort by height descending
            self._formats.sort(key=lambda x: int(x["text"].split("p")[0]), reverse=True)

            Clock.schedule_once(self._build_quality_menu)
        except Exception as e:
            Clock.schedule_once(lambda dt: self._show_dialog(f"Error loading formats: {e}"))

    @mainthread
    def _build_quality_menu(self, dt):
        if not self._formats:
            self._show_dialog("No video formats found.")
            self._set_status("Ready")
            return

        menu_items = [
            {
                "text": f["text"],
                "viewclass": "OneLineListItem",
                "on_release": lambda x=f["format_id"], y=f["text"]: self._select_quality(x, y),
            }
            for f in self._formats
        ]

        # *** CREATE MENU ONCE ***
        self.quality_menu = MDDropdownMenu(
            caller=self.root.ids.quality_btn,
            items=menu_items,
            width_mult=4,
        )

        # enable button + open menu immediately
        self.root.ids.quality_btn.disabled = False
        self.root.ids.quality_btn.text = "Quality"
        self._set_status("Formats loaded – choose quality")
        self.quality_menu.open()

    def _select_quality(self, fmt_id: str, text: str):
        self._selected_format = fmt_id
        self.root.ids.quality_btn.text = text.split(" – ")[0]   # show only resolution
        self.quality_menu.dismiss()

    def _reset_quality_selector(self):
        self.root.ids.quality_btn.text = "Quality"
        self.root.ids.quality_btn.disabled = True
        self._selected_format = None
        self._formats = []
        self.quality_menu = None

    # ------------------------------------------------------------------
    # Download logic
    # ------------------------------------------------------------------
    def start_download(self):
        url = self.root.ids.url_field.text.strip()
        if not url:
            return self._show_dialog("Please paste a YouTube URL.")
        if platform == 'android' and not (self._default_path or self._saf):
            return self._show_dialog("Folder error – restart the app.")
        if not self._selected_format:
            return self._show_dialog("Please select a quality first.")
        threading.Thread(target=self._download_thread, args=(url,), daemon=True).start()

    # ------------------------------------------------------------------
    def _download_thread(self, raw_url: str):
        self.progress = 0
        self._set_status("Preparing…")
        url = fix_shorts_url(raw_url)

        ydl_opts = {
            "format": self._selected_format,
            "noplaylist": True,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "outtmpl": "",  # will be set later
        }

        # ------------------- SAF folder -------------------
        if platform == 'android' and self._saf:
            info = yt_dlp.YoutubeDL({"quiet": True}).extract_info(url, download=False)
            title = info.get("title", "video")
            ext = info.get("ext", "mp4")
            safe_name = "".join(c if c not in r'\/:*?"<>|' else "_" for c in title)
            filename = f"{safe_name}.{ext}"
            file_uri = self._saf.create_file(filename)
            if not file_uri:
                self._set_status("Failed to create file in SAF folder")
                return

            class SAFOutput:
                def __init__(self, saf, uri):
                    self.saf = saf
                    self.uri = uri
                def __enter__(self):
                    self.fd = os.dup(self.saf.open_output_stream(self.uri).detachFd())
                    return self
                def __exit__(self, *args):
                    os.close(self.fd)

            def _my_hook(d):
                if d["status"] == "downloading":
                    self._progress_hook(d)
                elif d["status"] == "finished":
                    tmp_path = d["filepath"]
                    with open(tmp_path, "rb") as src, SAFOutput(self._saf, file_uri) as dst:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            os.write(dst.fd, chunk)
                    os.unlink(tmp_path)
                    self._progress_hook({"status": "finished"})

            ydl_opts["progress_hooks"] = [_my_hook]
            self._set_status(f"Downloading: {title}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        # ------------------- Default folder -------------------
        else:
            out_path = self._default_path if platform == 'android' else self.download_folder
            ydl_opts["outtmpl"] = os.path.join(out_path, "%(title)s.%(ext)s")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get("title", "video")
                    self._set_status(f"Downloading: {title}")
                    ydl.download([url])
            except Exception as e:
                self._set_status(f"Error: {e}")
                return

        self._set_status("Download finished")
        self._record_recent(title if 'title' in locals() else "Unknown")
        self.progress = 100

    # ------------------------------------------------------------------
    # Progress hook – also updates percent label
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
        self.root.ids.percent_label.text = f"{val} %"

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
    # Dialog helper
    # ------------------------------------------------------------------
    def _show_dialog(self, txt: str):
        MDDialog(title="Notice", text=txt, size_hint=(0.8, None)).open()

# ----------------------------------------------------------------------
if __name__ == "__main__":
    YouTubeDownloaderApp().run()
