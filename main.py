from kivy.lang import Builder
from kivymd.app import MDApp
from kivy.utils import platform
import os

# Embed KV directly in the code - DON'T use external files on Android
KV = '''
MDScreen:
    md_bg_color: 0.95, 0.95, 0.95, 1
    
    MDBoxLayout:
        orientation: "vertical"
        padding: "40dp"
        spacing: "20dp"
        pos_hint: {"center_x": 0.5, "center_y": 0.5}
        
        MDLabel:
            text: "Welcome to KivyMD!"
            halign: "center"
            font_style: "H4"
            theme_text_color: "Primary"
            size_hint_y: None
            height: self.texture_size[1]
        
        MDTextField:
            id: name_input
            hint_text: "Enter your name"
            size_hint_y: None
            height: "50dp"
            icon_left: "account"
        
        MDBoxLayout:
            orientation: "horizontal"
            spacing: "10dp"
            size_hint_y: None
            height: "50dp"
            pos_hint: {"center_x": 0.5}
            
            MDRaisedButton:
                text: "Greet Me"
                on_release: app.on_button_click()
            
            MDRaisedButton:
                text: "Clear"
                on_release: app.clear_text()
        
        MDLabel:
            id: greeting_label
            text: "Enter your name above!"
            halign: "center"
            theme_text_color: "Secondary"
            size_hint_y: None
            height: self.texture_size[1]
        
        MDRaisedButton:
            text: "App Info"
            size_hint_x: 0.5
            pos_hint: {"center_x": 0.5}
            on_release: app.show_info()
'''

class MainApp(MDApp):
    def build(self):
        # Set theme before loading KV
        self.theme_cls.theme_style = "Light"
        self.theme_cls.primary_palette = "Blue"
        
        # Load embedded KV string - NEVER use external files on Android
        try:
            return Builder.load_string(KV)
        except Exception as e:
            # If KivyMD fails, fall back to basic Kivy
            return self.create_basic_fallback_ui()
    
    def create_basic_fallback_ui(self):
        """Create basic UI without KivyMD if it fails"""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.textinput import TextInput
        from kivy.uix.button import Button
        
        layout = BoxLayout(orientation='vertical', padding=40, spacing=20)
        
        title = Label(text='Welcome!', font_size=24)
        layout.add_widget(title)
        
        self.name_input = TextInput(hint_text='Enter your name', size_hint_y=None, height=50)
        layout.add_widget(self.name_input)
        
        button = Button(text='Greet Me', size_hint_y=None, height=50)
        button.bind(on_press=self.basic_button_click)
        layout.add_widget(button)
        
        self.greeting_label = Label(text='Enter your name above!')
        layout.add_widget(self.greeting_label)
        
        return layout
    
    def basic_button_click(self, instance):
        """Button handler for basic fallback UI"""
        name = self.name_input.text.strip()
        if name:
            self.greeting_label.text = f"Hello, {name}! 👋"
        else:
            self.greeting_label.text = "Please enter your name!"
    
    def on_button_click(self):
        """Handle button click event"""
        try:
            name = self.root.ids.name_input.text.strip()
            if name:
                self.root.ids.greeting_label.text = f"Hello, {name}! 👋"
            else:
                self.root.ids.greeting_label.text = "Please enter your name!"
        except Exception as e:
            # If KivyMD widgets fail, show basic message
            self.show_basic_alert("Please enter a name")
    
    def clear_text(self):
        """Clear the text input and greeting"""
        try:
            self.root.ids.name_input.text = ""
            self.root.ids.greeting_label.text = "Enter your name above!"
        except:
            pass
    
    def show_info(self):
        """Show information - simplified for Android"""
        self.show_basic_alert("This is a simple KivyMD app for Android!")
    
    def show_basic_alert(self, message):
        """Show basic alert without dialogs"""
        try:
            from kivymd.uix.dialog import MDDialog
            from kivymd.uix.button import MDFlatButton
            
            dialog = MDDialog(
                title="Info",
                text=message,
                buttons=[
                    MDFlatButton(
                        text="OK",
                        on_release=lambda x: dialog.dismiss()
                    ),
                ],
            )
            dialog.open()
        except:
            # If dialogs fail, just update the label
            self.root.ids.greeting_label.text = message

if __name__ == "__main__":
    MainApp().run()
