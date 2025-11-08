from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
import os

class MainApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.dialog = None
    
    def build(self):
        # Set theme
        self.theme_cls.theme_style = "Light"
        self.theme_cls.primary_palette = "Blue"
        
        # Check if KV file exists
        if not os.path.exists("main.kv"):
            print("ERROR: main.kv file not found!")
            return self.create_fallback_ui()
        
        try:
            # Load KV file
            return Builder.load_file("main.kv")
        except Exception as e:
            print(f"Error loading KV file: {e}")
            return self.create_fallback_ui()
    
    def create_fallback_ui(self):
        """Create UI programmatically if KV file fails"""
        layout = MDBoxLayout(
            orientation="vertical",
            padding=40,
            spacing=30,
            pos_hint={"center_x": 0.5, "center_y": 0.5}
        )
        
        # Add widgets programmatically
        title = MDLabel(
            text="Welcome to KivyMD!",
            halign="center",
            font_style="H4",
            theme_text_color="Primary"
        )
        layout.add_widget(title)
        
        return layout
    
    def on_button_click(self):
        """Handle button click event"""
        try:
            name = self.root.ids.name_input.text.strip()
            
            if name:
                self.root.ids.greeting_label.text = f"Hello, {name}! 👋"
            else:
                self.root.ids.greeting_label.text = "Please enter your name!"
        except AttributeError as e:
            print(f"Widgets not found: {e}")
            self.show_alert_dialog("Error", "UI not loaded properly!")
    
    def show_info(self):
        """Show information dialog"""
        if not self.dialog:
            self.dialog = MDDialog(
                title="App Info",
                text="This is a simple KivyMD app with KV language!\n\nFeatures:\n• Material Design\n• Clean UI\n• Easy to extend",
                buttons=[
                    MDFlatButton(
                        text="OK",
                        theme_text_color="Custom",
                        text_color=self.theme_cls.primary_color,
                        on_release=lambda x: self.dialog.dismiss()
                    ),
                ],
            )
        self.dialog.open()
    
    def show_alert_dialog(self, title, text):
        """Show alert dialog"""
        dialog = MDDialog(
            title=title,
            text=text,
            buttons=[
                MDFlatButton(
                    text="OK",
                    theme_text_color="Custom",
                    text_color=self.theme_cls.primary_color,
                    on_release=lambda x: dialog.dismiss()
                ),
            ],
        )
        dialog.open()
    
    def clear_text(self):
        """Clear the text input and greeting"""
        try:
            self.root.ids.name_input.text = ""
            self.root.ids.greeting_label.text = "Enter your name above!"
        except AttributeError:
            self.show_alert_dialog("Error", "UI not loaded properly!")

if __name__ == "__main__":
    MainApp().run()
