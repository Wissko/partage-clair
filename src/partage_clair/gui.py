"""Small Tk desktop interface; documents stay in process memory and on local disk."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .core import Box, Document


class App:
    def __init__(self, root):
        self.root = root
        self.doc = None
        self.boxes = []
        self.page = 0
        self.drag = None
        self.preview = None
        self.photo = None
        self.area = (0, 0, 1, 1)
        root.title("Partage Clair — préparer, vérifier, partager")
        root.geometry("1080x830")
        root.minsize(780, 620)
        root.configure(bg="#f1f3ee")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f1f3ee")
        style.configure("TLabel", background="#f1f3ee", foreground="#20342c", font=("Segoe UI", 11))
        style.configure("Title.TLabel", font=("Segoe UI", 25, "bold"))
        style.configure("TButton", padding=(12, 8), font=("Segoe UI", 10))
        style.configure("Accent.TButton", background="#235c47", foreground="white")
        frame = ttk.Frame(root, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Partage Clair", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="PDF & images • Traitement local • Aucun compte").pack(anchor="w", pady=(2, 12))
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        ttk.Button(bar, text="1. Ouvrir un fichier", command=self.open).pack(side="left")
        self.prev = ttk.Button(bar, text="←", command=lambda: self.move(-1), state="disabled")
        self.prev.pack(side="left", padx=(15, 3))
        self.counter = ttk.Label(bar, text="Aucun document")
        self.counter.pack(side="left", padx=8)
        self.next = ttk.Button(bar, text="→", command=lambda: self.move(1), state="disabled")
        self.next.pack(side="left", padx=3)
        self.undo = ttk.Button(bar, text="Annuler le dernier masque", command=self.undo_mask, state="disabled")
        self.undo.pack(side="right")
        ttk.Label(frame, text="2. Tracez un rectangle sur chaque information à cacher.").pack(anchor="w", pady=10)
        self.canvas = tk.Canvas(frame, bg="#dce2dc", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.canvas.bind("<ButtonPress-1>", self.start)
        self.canvas.bind("<B1-Motion>", self.motion)
        self.canvas.bind("<ButtonRelease-1>", self.finish)
        self.status = tk.StringVar(value="Ouvrez un PDF, un PNG, un JPEG ou un WebP statique.")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(10, 3))
        ttk.Label(frame, text="Les PDF exportés perdent le texte sélectionnable, les liens, les formulaires et les signatures.",
                  wraplength=980).pack(anchor="w", pady=(2, 9))
        foot = ttk.Frame(frame)
        foot.pack(fill="x")
        ttk.Label(foot, text="PDF : résolution de sortie").pack(side="left")
        self.dpi = tk.StringVar(value="150")
        ttk.Combobox(foot, textvariable=self.dpi, values=("72", "100", "150", "200"),
                     width=5, state="readonly").pack(side="left", padx=8)
        self.save = ttk.Button(foot, text="3. Exporter une copie…", command=self.export,
                               style="Accent.TButton", state="disabled")
        self.save.pack(side="right")
        root.protocol("WM_DELETE_WINDOW", self.close)

    def open(self):
        path = filedialog.askopenfilename(filetypes=[
            ("PDF et images", "*.pdf *.png *.jpg *.jpeg *.webp"),
        ])
        if not path:
            return
        candidate = None
        try:
            candidate = Document(path)
            preview = candidate.render(0, 90)
        except Exception as error:
            if candidate:
                candidate.close()
            messagebox.showerror("Ouverture impossible", str(error))
            return
        if self.doc:
            self.doc.close()
        if self.preview:
            self.preview.close()
        self.doc = candidate
        self.preview = preview
        self.boxes = []
        self.page = 0
        self.drag = None
        self.save.configure(state="normal")
        self.draw()

    def move(self, delta):
        if not self.doc:
            return
        index = self.page + delta
        if not 0 <= index < self.doc.pages:
            return
        try:
            preview = self.doc.render(index, 90)
        except Exception as error:
            messagebox.showerror("Page indisponible", str(error))
            return
        self.preview.close()
        self.preview = preview
        self.page = index
        self.drag = None
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if not self.preview:
            self.canvas.create_text(cw / 2, ch / 2, text="Votre document reste sur cet ordinateur.",
                                    fill="#50655a", font=("Segoe UI", 15))
            return
        if cw < 30 or ch < 30:
            return
        image = self.preview.copy()
        image.thumbnail((cw - 24, ch - 24), Image.Resampling.LANCZOS)
        w, h = image.size
        x, y = (cw - w) / 2, (ch - h) / 2
        self.area = (x, y, w, h)
        self.photo = ImageTk.PhotoImage(image)
        image.close()
        self.canvas.create_image(x, y, image=self.photo, anchor="nw")
        for box in self.boxes:
            if box.page == self.page + 1:
                self.canvas.create_rectangle(x + box.x0 * w, y + box.y0 * h,
                                             x + box.x1 * w, y + box.y1 * h,
                                             fill="black", outline="black")
        self.counter.configure(text=f"Page {self.page + 1} / {self.doc.pages}")
        self.prev.configure(state="normal" if self.page > 0 else "disabled")
        self.next.configure(state="normal" if self.page + 1 < self.doc.pages else "disabled")
        self.undo.configure(state="normal" if self.boxes else "disabled")
        self.status.set(f"{len(self.boxes)} masque(s) dans le document. Métadonnées retirées à l'export.")

    def point(self, event):
        x, y, w, h = self.area
        return max(0, min(1, (event.x - x) / w)), max(0, min(1, (event.y - y) / h))

    def start(self, event):
        if self.doc:
            x, y, w, h = self.area
            if x <= event.x <= x + w and y <= event.y <= y + h:
                self.drag = self.point(event)

    def motion(self, event):
        self.canvas.delete("drag")
        if self.drag:
            px, py = self.point(event)
            x, y, w, h = self.area
            self.canvas.create_rectangle(x + self.drag[0] * w, y + self.drag[1] * h,
                                         x + px * w, y + py * h, outline="#c25723", width=3,
                                         fill="#333333", stipple="gray50", tags="drag")

    def finish(self, event):
        if not self.drag:
            return
        px, py = self.point(event)
        x0, x1 = sorted((self.drag[0], px))
        y0, y1 = sorted((self.drag[1], py))
        self.drag = None
        if (x1 - x0) * self.area[2] >= 2 and (y1 - y0) * self.area[3] >= 2:
            self.boxes.append(Box(self.page + 1, x0, y0, x1, y1))
        self.draw()

    def undo_mask(self):
        if self.boxes:
            box = self.boxes.pop()
            if box.page != self.page + 1:
                self.move(box.page - 1 - self.page)
            self.draw()

    def export(self):
        if not self.doc:
            return
        if not messagebox.askokcancel("Vérifier avant de partager",
                "Les informations visibles non masquées restent lisibles.\n\n"
                "Vérifiez chaque page, les noms, codes QR et codes-barres. "
                "L'outil ne les détecte pas automatiquement.\n\n"
                "Le PDF sera une copie en images, sans signature numérique valide. Continuer ?"):
            return
        ext = ".pdf" if self.doc.kind == "pdf" else ".png"
        target = filedialog.asksaveasfilename(initialfile=f"document-a-partager{ext}",
                    defaultextension=ext, filetypes=[("Copie de partage", f"*{ext}")])
        if not target:
            return
        self.save.configure(state="disabled")
        self.status.set("Export local en cours…")
        self.root.update_idletasks()
        try:
            result = self.doc.export(Path(target), self.boxes, int(self.dpi.get()))
        except Exception as error:
            messagebox.showerror("Export refusé", str(error))
            self.draw()
        else:
            self.status.set("Copie créée. Ouvrez-la et relisez toutes les pages avant de partager.")
            messagebox.showinfo("Copie créée", f"{result}\n\nOuvrez la copie exportée pour vérifier le résultat.")
        finally:
            self.save.configure(state="normal")

    def close(self):
        if self.doc:
            self.doc.close()
        if self.preview:
            self.preview.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
