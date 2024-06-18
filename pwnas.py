import os
import logging
import threading
import subprocess
from flask import Flask, render_template_string, send_from_directory, request, redirect, url_for, abort
from pwnagotchi import plugins
import signal
import requests

UPLOAD_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>NAS Server</title>
  </head>
  <body>
    <h1>NAS Server</h1>
    <p>Your NAS server is running at <a href="/files/">/files/</a>.</p>
    <h2>Upload File</h2>
    <form action="/upload" method="post" enctype="multipart/form-data">
        <input type="file" name="file">
        <input type="submit" value="Upload">
    </form>
    <h2>Files</h2>
    <form action="/delete" method="post">
        <ul>
        {% for file in files %}
            <li>
                <a href="/files/{{ file }}">{{ file }}</a>
                <input type="checkbox" name="delete_files" value="{{ file }}">
            </li>
        {% endfor %}
        </ul>
        <input type="submit" value="Delete Selected">
    </form>
  </body>
</html>
"""

app = Flask(__name__)

@app.route('/')
def index():
    return nas_server_plugin.render_upload_page()

@app.route('/files/')
def files():
    return nas_server_plugin.serve_files_index()

@app.route('/files/<path:filename>')
def download(filename):
    return nas_server_plugin.serve_file(filename)

@app.route('/upload', methods=['POST'])
def upload():
    return nas_server_plugin.upload_file(request)

@app.route('/delete', methods=['POST'])
def delete():
    return nas_server_plugin.delete_files(request)

@app.route('/shutdown', methods=['POST'])
def shutdown():
    shutdown_server()
    return 'Server shutting down...'

def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

class NasServer(plugins.Plugin):
    __GitHub__ = ""
    __author__ = "your_name <your_email>"
    __version__ = "1.0.4"
    __license__ = "GPL3"
    __description__ = "A plugin to turn Pwnagotchi into a NAS server using Samba."
    __name__ = "NasServer"
    __help__ = "A plugin that sets up a NAS server on the Pwnagotchi device using Samba."
    __dependencies__ = {
        "apt": ["samba"],
    }
    __defaults__ = {
        "enabled": False,
    }

    def __init__(self):
        self.shared_folder = '/root/nas_shared'
        self.samba_conf = '/etc/samba/smb.conf'
        self.samba_service = 'smbd'
        self.http_server_thread = None

    def on_loaded(self):
        logging.info(f"[{self.__class__.__name__}] plugin loaded")
        try:
            self.setup_shared_folder()
            self.setup_samba()
            self.start_samba()
            self.start_http_server()
        except Exception as e:
            logging.error(f"[{self.__class__.__name__}] Error during initialization: {e}")

    def on_unload(self, *args):
        logging.info(f"[{self.__class__.__name__}] plugin unloaded")
        try:
            self.stop_samba()
            self.stop_http_server()
        except Exception as e:
            logging.error(f"[{self.__class__.__name__}] Error during unload: {e}")

    def setup_shared_folder(self):
        if not os.path.exists(self.shared_folder):
            os.makedirs(self.shared_folder)
            logging.info(f"[{self.__class__.__name__}] Created shared folder at {self.shared_folder}")
        else:
            logging.info(f"[{self.__class__.__name__}] Shared folder already exists at {self.shared_folder}")

    def setup_samba(self):
        samba_conf_content = f"""
[global]
    workgroup = WORKGROUP
    server string = Pwnagotchi NAS Server
    netbios name = Pwnagotchi
    security = user
    map to guest = Bad User
    dns proxy = no

[nas_shared]
    path = {self.shared_folder}
    browsable = yes
    writable = yes
    guest ok = yes
    read only = no
    create mask = 0755
"""
        with open(self.samba_conf, 'w') as conf_file:
            conf_file.write(samba_conf_content)
            logging.info(f"[{self.__class__.__name__}] Samba configuration written to {self.samba_conf}")

    def start_samba(self):
        result = subprocess.run(['systemctl', 'restart', self.samba_service], capture_output=True)
        if result.returncode == 0:
            logging.info(f"[{self.__class__.__name__}] Samba service started successfully")
        else:
            logging.error(f"[{self.__class__.__name__}] Failed to start Samba service: {result.stderr.decode()}")

    def stop_samba(self):
        result = subprocess.run(['systemctl', 'stop', self.samba_service], capture_output=True)
        if result.returncode == 0:
            logging.info(f"[{self.__class__.__name__}] Samba service stopped successfully")
        else:
            logging.error(f"[{self.__class__.__name__}] Failed to stop Samba service: {result.stderr.decode()}")

    def start_http_server(self):
        try:
            self.http_server_thread = threading.Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 8000})
            self.http_server_thread.daemon = True
            self.http_server_thread.start()
            logging.info(f"[{self.__class__.__name__}] HTTP server started at http://0.0.0.0:8000/")
        except Exception as e:
            logging.error(f"[{self.__class__.__name__}] Failed to start HTTP server: {e}")

    def stop_http_server(self):
        if self.http_server_thread:
            try:
                requests.post('http://127.0.0.1:8000/shutdown')
                self.http_server_thread.join()
                logging.info(f"[{self.__class__.__name__}] HTTP server stopped")
            except Exception as e:
                logging.error(f"[{self.__class__.__name__}] Failed to stop HTTP server: {e}")

    def render_upload_page(self):
        try:
            files = os.listdir(self.shared_folder)
            return render_template_string(UPLOAD_TEMPLATE, files=files)
        except Exception as e:
            logging.error(f"[{self.__class__.__name__}] Failed to render upload page: {e}")
            abort(500)

    def serve_files_index(self):
        try:
            files = os.listdir(self.shared_folder)
            file_links = [f'<a href="/files/{file}">{file}</a>' for file in files]
            return "<br>".join(file_links)
        except Exception as e:
            logging.error(f"[{self.__class__.__name__}] Failed to serve file index: {e}")
            abort(500)

    def serve_file(self, filename):
        try:
            logging.info(f"[{self.__class__.__name__}] Serving file: {filename}")
            return send_from_directory(self.shared_folder, filename)
        except Exception as e:
            logging.error(f"[{self.__class__.__name__}] Failed to serve file {filename}: {e}")
            abort(500)

    def upload_file(self, request):
        if 'file' not in request.files:
            logging.error(f"[{self.__class__.__name__}] No file part in the request")
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            logging.error(f"[{self.__class__.__name__}] No selected file")
            return redirect(request.url)
        if file:
            filename = file.filename
            file.save(os.path.join(self.shared_folder, filename))
            logging.info(f"[{self.__class__.__name__}] File {filename} uploaded successfully")
            return redirect(url_for('index'))

    def delete_files(self, request):
        try:
            files_to_delete = request.form.getlist('delete_files')
            for filename in files_to_delete:
                os.remove(os.path.join(self.shared_folder, filename))
                logging.info(f"[{self.__class__.__name__}] File {filename} deleted successfully")
            return redirect(url_for('index'))
        except Exception as e:
            logging.error(f"[{self.__class__.__name__}] Failed to delete files: {e}")
            abort(500)

# The instance of the NasServer plugin
nas_server_plugin = NasServer()
