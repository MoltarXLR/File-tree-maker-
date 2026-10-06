"""Developer tool: screenshots of the real window on a Windows machine.

Run by .github/workflows/screenshots.yml.  Each picture is printed into the job log as base64
between BEGIN/END markers (so it can be read back without downloading an artifact).
"""

import base64
import io
import os
import sys
import tempfile
import time
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageGrab

sys.path.insert(0, os.getcwd())

from foldertemplatemaker import model, osutil  # noqa: E402
from foldertemplatemaker.dialogs import DocumentDialog  # noqa: E402
from foldertemplatemaker.gui import App  # noqa: E402
from foldertemplatemaker.model import Folder, Template  # noqa: E402
from foldertemplatemaker.storage import Store  # noqa: E402


def emit(name, image):
    buffer = io.BytesIO()
    image.convert("RGB").quantize(colors=256).save(buffer, format="PNG", optimize=True)
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    print("=====BEGIN %s %d" % (name, len(data)))
    for start in range(0, len(data), 100):
        print(data[start:start + 100])
    print("=====END %s" % name, flush=True)


tmp = tempfile.mkdtemp()
os.environ[osutil.HOME_ENV_VAR] = os.path.join(tmp, "data")
destination = os.path.join(tmp, "OneDrive - Contoso", "Deals")
os.makedirs(destination)

osutil.enable_dpi_awareness()
store = Store()
store.load()
extra = Folder("Litigation matter")
for name in ("Pleadings", "Discovery", "Correspondence"):
    model.add_folder(extra, name)
store.add(Template("Litigation template", extra))
store.settings.remember_destination(store.templates[0].id, destination)
store.settings.last_template_id = store.templates[0].id

app = App(store)
app.geometry("+0+0")
app.attributes("-topmost", True)


def settle(rounds=14):
    for _ in range(rounds):
        app.update()
        time.sleep(0.1)
    app.lift()
    app.focus_force()
    for _ in range(4):
        app.update()
        time.sleep(0.1)


settle()
print("windowing system:", app.tk.call("tk", "windowingsystem"))
print("ttk theme:", ttk.Style(app).theme_use())
print("tk scaling:", app.tk.call("tk", "scaling"), " app.scale:", app.scale)
print("screen:", app.winfo_screenwidth(), "x", app.winfo_screenheight())
print("window:", app.geometry(), " min:", app.minsize())
print("default font:", tkfont.nametofont("TkDefaultFont").actual())
print("icon loaded:", app.icon_loaded)

emit("main", ImageGrab.grab())

work = app.current.root.folders[1]
app.editor.select(work)
app.editor.add_subfolder()
settle(6)
emit("editing", ImageGrab.grab())
app.editor._abort_edit()

dialog = DocumentDialog(
    app, title="Edit document", folder_name="Work product", name="{title} raw data", ext=".txt",
    content="Raw data - {title}\nCreated {date_long}\n\n",
    preview=lambda n, e: n.replace("{title}", "Xcom Diligence") + e, apply=lambda *a: None,
    modal=False)
dialog.attributes("-topmost", True)
dialog.present()
settle(6)
emit("docdialog", ImageGrab.grab())
dialog.destroy()

app.error = lambda title, message: print("ERROR DIALOG:", title, message)
app.dest_var.set(destination)
app.name_var.set("Xcom Diligence")
app.create()
settle(6)
emit("created", ImageGrab.grab())
print("created folders:", sorted(os.listdir(os.path.join(destination, "Xcom Diligence"))))
app.destroy()
