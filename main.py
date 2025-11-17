from kivy.lang import Builder
from kivymd.app import MDApp
from kivy.utils import platform
import os

from kivy.lang import Builder
from kivy.clock import Clock
from kivy.properties import StringProperty, NumericProperty, ListProperty
from kivy.utils import platform
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.storage.jsonstore import JsonStore

from kivymd.app import MDApp
from kivymd.uix.filemanager import MDFileManager
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import OneLineListItem
from kivymd.toast import toast

import threading
import os
import datetime

# try importing yt_dlp or pytube; fallback to no-op
try:
    import yt_dlp as ytdl
    _DOWNLOADER = 'yt_dlp'
except Exception:
    try:
        from pytube import YouTube
        _DOWNLOADER = 'pytube'
    except Exception:
        _DOWNLOADER = None

KV = r"""
BoxLayout:
    orientation: 'vertical'
    spacing: dp(10)
    padding: dp(12)

    MDToolbar:
        title: app.title
        elevation: 10
        left_action_items: [['youtube', lambda x: None]]

    BoxLayout:
        size_hint_y: None
        height: self.minimum_height
        spacing: dp(10)

        MDCard:
            size_hint: None, None
            size: root.card_width, dp(180)
            elevation: 6
            padding: dp(12)
            pos_hint: {'center_x': .5}

            BoxLayout:
                orientation: 'vertical'
                spacing: dp(8)

                MDTextField:
                    id: url_field
                    hint_text: 'YouTube video URL'
                    required: True
                    helper_text_mode: 'on_error'
                    size_hint_x: 1

                BoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    spacing: dp(8)

                    MDLabel:
                        text: 'Quality:'
                        size_hint_x: None
                        width: dp(70)
                        valign: 'middle'

                    MDDropDownItem:
                        id: quality_dd
                        text: 'Best available'
                        on_release: app.open_quality_menu(self)

                    Widget:

                    MDFillRoundFlatIconButton:
                        text: 'Choose Folder'
                        icon: 'folder'
                        on_release: app.open_file_manager()

                BoxLayout:
                    size_hint_y: None
                    height: dp(36)
                    spacing: dp(8)

                    MDLabel:
                        id: folder_label
                        text: root.download_folder if root.download_folder else 'No folder selected'
                        theme_text_color: 'Secondary'
                        shorten: True

                BoxLayout:
                    size_hint_y: None
                    height: dp(48)
                    spacing: dp(8)

                    MDRaisedButton:
                        text: 'Download'
                        on_release: app.on_download_click()

                    MDFlatButton:
                        text: 'Clear'
                        on_release: app.clear_inputs()

    MDProgressBar:
        id: progress
        value: root.progress_value
        type: 'determinate'

    BoxLayout:
        orientation: 'horizontal'
        size_hint_y: None
        height: dp(160)
        spacing: dp(10)

        MDCard:
            md_bg_color: app.theme_cls.bg_darkest
            elevation: 4
            padding: dp(8)
            size_hint_x: 0.6

            BoxLayout:
                orientation: 'vertical'
                spacing: dp(6)

                MDLabel:
                    text: 'Status'
                    font_style: 'Subtitle1'

                MDLabel:
                    id: status_label
                    text: root.status_text
                    theme_text_color: 'Secondary'
                    halign: 'left'
                    valign: 'top'
                    size_hint_y: None
                    height: dp(100)

        MDCard:
            elevation: 4
            padding: dp(8)
            size_hint_x: 0.4

            BoxLayout:
                orientation: 'vertical'

                MDLabel:
                    text: 'Recent Downloads'
                    font_style: 'Subtitle1'

                ScrollView:
                    MDList:
                        id: recent_list

    Widget:
        size_hint_y: None
        height: dp(8)

"""
class YouTubeDownloaderApp(MDApp):
    title = "YouTube Downloader"
    download_folder = StringProperty('')
    progress_value = NumericProperty(0)
    status_text = StringProperty('Ready')
    recent = ListProperty([])
    card_width = NumericProperty(dp(680))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.file_manager = None
        self.store = JsonStore('ytdl_store.json')
        if self.store.exists('downloads'):
            self.recent = self.store.get('downloads')['items']
        else:
            self.recent = []

    def build(self):
        self.theme_cls.primary_palette = 'Red'
        self.theme_cls.theme_style = 'Light'
        root = Builder.load_string(KV)
        Clock.schedule_once(self.post_build_init, 0)
        return root

    def post_build_init(self, *args):
        # adapt card width for smaller screens
        if Window.width < dp(700):
            self.card_width = Window.width - dp(36)
        self.populate_recent()

    def populate_recent(self):
        lst = self.root.ids.recent_list
        lst.clear_widgets()
        for item in reversed(self.recent[-10:]):
            li = OneLineListItem(text=f"{item['title']} — {item['time']}")
            lst.add_widget(li)

    def open_file_manager(self):
        if not self.file_manager:
            self.file_manager = MDFileManager(
                exit_manager=self.exit_file_manager,
                select_path=self.select_path,
                preview=False,
            )
        self.file_manager.show(os.path.expanduser('~'))

    def exit_file_manager(self, *args):
        self.file_manager.close()

    def select_path(self, path):
        self.download_folder = path
        self.root.ids.folder_label.text = path
        self.exit_file_manager()

    def open_quality_menu(self, widget):
        # Simplified static options; you can expand to probe available streams
        from kivymd.uix.menu import MDDropdownMenu
        menu_items = [
            {"text": "Best available"},
            {"text": "Audio only (mp3)"},
            {"text": "1080p if available"},
            {"text": "720p"},
            {"text": "480p"},
        ]
        menu = MDDropdownMenu(caller=widget, items=menu_items, width_mult=4)
        menu.open()

    def clear_inputs(self):
        self.root.ids.url_field.text = ''
        self.root.ids.quality_dd.text = 'Best available'
        self.progress_value = 0
        self.status_text = 'Ready'

    def on_download_click(self):
        url = self.root.ids.url_field.text.strip()
        if not url:
            self.show_dialog('Please paste a YouTube URL first.')
            return
        if not self.download_folder:
            self.show_dialog('Please choose a destination folder.')
            return
        # start threaded download
        threading.Thread(target=self._download_thread, args=(url, self.root.ids.quality_dd.text), daemon=True).start()

    def _download_thread(self, url, quality):
        self.progress_value = 0
        self.status_text = 'Starting download...'
        Clock.schedule_once(lambda dt: None)

        try:
            if _DOWNLOADER == 'yt_dlp':
                self._download_with_ytdl(url, quality)
            elif _DOWNLOADER == 'pytube':
                self._download_with_pytube(url, quality)
            else:
                raise RuntimeError('No downloader library installed (yt_dlp or pytube).')
        except Exception as e:
            self._update_status(f'Error: {e}')

    def _download_with_ytdl(self, url, quality):
        opts = {
            'outtmpl': os.path.join(self.download_folder, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'progress_hooks': [self._ytdl_progress_hook],
            'format': 'best'
        }
        if 'Audio' in quality:
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        elif '1080' in quality:
            opts['format'] = 'bv*+ba/best[height<=1080]'
        elif '720' in quality:
            opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
        elif '480' in quality:
            opts['format'] = 'best[height<=480]'

        with ytdl.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'video')
            self._update_status(f'Downloading: {title}')
            ydl.download([url])
            self._update_status('Download finished')
            self._record_recent(title)
            self.progress_value = 100

    def _ytdl_progress_hook(self, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            try:
                percent = int(downloaded / total * 100) if total else 0
            except Exception:
                percent = 0
            self.progress_value = percent
            self._update_status(f"Downloading... {percent}%")
        elif d['status'] == 'finished':
            self.progress_value = 100
            self._update_status('Processing finished...')

    def _download_with_pytube(self, url, quality):
        yt = YouTube(url, on_progress_callback=self._pytube_progress)
        stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
        if not stream:
            raise RuntimeError('No suitable stream found')
        title = yt.title
        self._update_status(f'Downloading: {title}')
        out = stream.download(output_path=self.download_folder)
        self._update_status('Download finished')
        self._record_recent(title)
        self.progress_value = 100

    def _pytube_progress(self, stream, chunk, bytes_remaining):
        total = stream.filesize
        downloaded = total - bytes_remaining
        percent = int(downloaded / total * 100)
        self.progress_value = percent
        self._update_status(f'Downloading... {percent}%')

    def _update_status(self, text):
        # called from background thread
        Clock.schedule_once(lambda dt: setattr(self, 'status_text', text))

    def _record_recent(self, title):
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        self.recent.append({'title': title, 'time': now})
        self.store.put('downloads', items=self.recent)
        Clock.schedule_once(lambda dt: self.populate_recent())

    def show_dialog(self, text):
        dlg = MDDialog(title='Notice', text=text, size_hint=(0.8, None), height=dp(180))
        dlg.open()


if __name__ == '__main__':
    YouTubeDownloaderApp().run()
