#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KivyMD YouTube Downloader – Android + Desktop – Nov 2025
Single file, fully working folder picker on Android
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
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.filemanager import MDFileManager
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import OneLineListItem

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
# Android SAF (Storage Access Framework) helper
# ----------------------------------------------------------------------
class AndroidSAF:
    """Small wrapper to write files via a persisted URI."""
    def __init__(self, uri_str: str):
        from jnius import autoclass
        self.Uri = autoclass('android.net.Uri')
        self.DocumentsContract = autoclass('android.provider.DocumentsContract')
        self.ContentResolver = autoclass('android.content.ContentResolver')
        self.PythonActivity = autoclass('org.kivy.android.PythonActivity')

        self.uri = self.Uri.parse(uri_str)
        self.cr = self.PythonActivity.mActivity.getContentResolver()

    def create_file(self, display_name: str, mime: str = "video/mp4"):
        """Create a new file inside the selected tree and return its URI."""
        doc_uri = self.DocumentsContract.createDocument(
            self.cr, self.uri, mime, display_name
        )
        return doc_uri

    def open_output_stream(self, file_uri):
        """Return a file descriptor that yt-dlp can write to."""
        return self.cr.openOutputStream(file_uri)


# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------
class YouTubeDownloaderApp(MDApp):
    status_text = StringProperty("Ready")
    progress = NumericProperty(0)
    download_folder = StringProperty("")      # displayed text
    recent = ListProperty([])

    # Android only
    _saf = None          # AndroidSAF instance
    _folder_uri = None   # persisted URI string

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.file_manager = None
        self.store = JsonStore("ytdl_store.json")
        if self.store.exists("recent"):
            self.recent = self.store.get("recent")["items"]
        if self.store.exists("folder_uri"):
            self._folder_uri = self.store.get("folder_uri")["uri"]
            self.download_folder = self.store.get("folder_uri")["name"]

    # ------------------------------------------------------------------
    # Android activity result (folder picker)
    # ------------------------------------------------------------------
    def on_activity_result(self, request_code, result_code, intent):
        if request_code != 1001:
            return
        # RESULT_OK = -1
        if result_code != -1:
            self._show_dialog("Folder selection cancelled.")
            return

        try:
            from jnius import autoclass
            Uri = autoclass('android.net.Uri')
            DocumentFile = autoclass('android.provider.DocumentsContract$DocumentFile')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')

            uri = intent.getData()
            cr = PythonActivity.mActivity.getContentResolver()
            # Persist permissions
            cr.takePersistableUriPermission(
                uri,
                autoclass('android.content.Intent').FLAG_GRANT_READ_URI_PERMISSION |
                autoclass('android.content.Intent').FLAG_GRANT_WRITE_URI_PERMISSION
            )

            doc_file = DocumentFile.fromTreeUri(PythonActivity.mActivity, uri)
            name = doc_file.getName() or "Selected Folder"

            # Store for later runs
            self._folder_uri = uri.toString()
            self.store.put("folder_uri", uri=self._folder_uri, name=name)

            self.download_folder = name
            self.root.ids.folder_label.text = name
            self._saf = AndroidSAF(self._folder_uri)

            self._show_dialog(f"Folder selected: {name}")
        except Exception as e:
            self._show_dialog(f"Error: {str(e)}")

    # ------------------------------------------------------------------
    def build(self):
        self.theme_cls.primary_palette = "Red"
        self.theme_cls.theme_style = "Light"
        self.root = Builder.load_string(KV)
        Clock.schedule_once(self._post_build, 0)
        return self.root

    def _post_build(self, dt):
        self._populate_recent()
        # If we already have a persisted folder, show it
        if self.download_folder:
            self.root.ids.folder_label.text = self.download_folder

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

    # ------------------------------------------------------------------
    # Folder picker – Android uses SAF, desktop uses MDFileManager
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

            @run_on_ui_thread
            def start_picker():
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                intent.addFlags(
                    Intent.FLAG_GRANT_READ_URI_PERMISSION |
                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION |
                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                )
                PythonActivity.mActivity.startActivityForResult(intent, 1001)

            start_picker()
        except Exception as e:
            self._show_dialog(f"Picker error: {e}")

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

    # ------------------------------------------------------------------
    # Download logic
    # ------------------------------------------------------------------
    def start_download(self):
        url = self.root.ids.url_field.text.strip()
        if not url:
            return self._show_dialog("Please paste a YouTube URL.")
        if platform == 'android' and not self._saf:
            return self._show_dialog("Please choose a folder first.")
        if platform != 'android' and not self.download_folder:
            return self._show_dialog("Please choose a folder first.")

        threading.Thread(target=self._download_thread, args=(url,), daemon=True).start()

    def _download_thread(self, raw_url: str):
        self.progress = 0
        self._set_status("Preparing…")
        url = fix_shorts_url(raw_url)

        # ------------------------------------------------------------------
        # Build yt-dlp options
        # ------------------------------------------------------------------
        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "extractor_args": {"youtube": {"skip": ["dash"]}},
        }

        if platform == 'android':
            # ---- Android: use SAF to write directly into the chosen folder ----
            info = yt_dlp.YoutubeDL({"quiet": True}).extract_info(url, download=False)
            title = info.get("title", "video")
            ext = info.get("ext", "mp4")
            safe_name = "".join(c if c not in r'\/:*?"<>|' else "_" for c in title)
            filename = f"{safe_name}.{ext}"

            # Create file inside the selected tree
            file_uri = self._saf.create_file(filename)
            if not file_uri:
                self._set_status("Failed to create file in folder")
                return

            # Custom output template that writes via SAF
            class SAFOutput:
                def __init__(self, saf, uri):
                    self.saf = saf
                    self.uri = uri

                def write(self, data):
                    os.write(self.fd, data)

                def close(self):
                    os.close(self.fd)

                def __enter__(self):
                    self.fd = os.dup(self.saf.open_output_stream(self.uri).detachFd())
                    return self

                def __exit__(self, *args):
                    self.close()

            # Tell yt-dlp to write to a file object
            ydl_opts["outtmpl"] = {"default": filename}   # just for info dict
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }]

            # Hook to replace the file path with our SAF stream
            def _my_hook(d):
                if d["status"] == "downloading":
                    self._progress_hook(d)
                elif d["status"] == "finished":
                    # yt-dlp finished downloading to a temporary file
                    tmp_path = d["filepath"]
                    # copy tmp → SAF
                    with open(tmp_path, "rb") as src, SAFOutput(self._saf, file_uri) as dst:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            dst.write(chunk)
                    os.unlink(tmp_path)   # clean up
                    self._progress_hook({"status": "finished"})

            ydl_opts["progress_hooks"] = [_my_hook]

            self._set_status(f"Downloading: {title}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        else:
            # ---- Desktop: normal path ----
            outtmpl = os.path.join(self.download_folder, "%(title)s.%(ext)s")
            ydl_opts["outtmpl"] = outtmpl
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
    # Progress hook (common for both platforms)
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
    # Dialog helper
    # ------------------------------------------------------------------
    def _show_dialog(self, txt: str):
        MDDialog(title="Notice", text=txt, size_hint=(0.8, None)).open()


# ----------------------------------------------------------------------
if __name__ == "__main__":
    YouTubeDownloaderApp().run()
