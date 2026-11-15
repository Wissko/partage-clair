"""Tk on the main thread, decoding and export on a serial document worker."""

import argparse
import math
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from queue import Empty
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import __version__
from .core import Box, ExportCancelled
from .worker import DocumentWorker


class App:
    def __init__(self, root, initial_path=None):
        self.root, self.worker = root, DocumentWorker()
        self.doc, self.preview, self.photo = None, None, None
        self.boxes, self.history, self.future = [], [], []
        self.approved = {}
        self.choices = {}
        self.report, self.review, self.preview_finding = None, None, None
        self.assurance_window = None
        self.analysis_revision = 0
        self.purpose, self.audience = '', ''
        self.criteria_snapshot, self.copy_snapshot = None, None
        self.audit, self.audit_snapshot = None, None
        self.score_cache = None
        self.exported, self.visited = self.mask_state(), set()
        self.page, self.zoom, self.preview_dpi = 0, 1.0, 90
        self.drag, self.selected, self.busy, self.pending = None, None, None, None
        self.closing, self.redraw_after, self.last_output = False, None, None
        self.area = (0, 0, 1, 1)
        root.title(f'Partage Clair {__version__} — préparer, vérifier, partager')
        root.geometry('1120x840')
        root.minsize(860, 650)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TFrame', background='#f1f3ee')
        style.configure('TLabel', background='#f1f3ee', foreground='#20342c', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 24, 'bold'))
        style.configure('TButton', padding=(9, 7), font=('Segoe UI', 10))
        style.configure('Accent.TButton', background='#235c47', foreground='white')
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Partage Clair', style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame, text='PDF & images • Traitement local • Aucun compte').pack(anchor='w', pady=(0, 10))
        bar = ttk.Frame(frame)
        bar.pack(fill='x')
        self.open_button = ttk.Button(bar, text='Ouvrir…', command=self.open)
        self.open_button.pack(side='left')
        self.prev = ttk.Button(bar, text='←', command=lambda: self.move(-1))
        self.prev.pack(side='left', padx=(12, 2))
        self.counter = ttk.Label(bar, text='Aucun document')
        self.counter.pack(side='left', padx=6)
        self.next = ttk.Button(bar, text='→', command=lambda: self.move(1))
        self.next.pack(side='left', padx=2)
        self.zoom_value = tk.StringVar(value='Adapter')
        self.zoom_choice = ttk.Combobox(bar, textvariable=self.zoom_value,
            values=('Adapter', '125 %', '150 %', '200 %', '300 %', '400 %'), width=9, state='readonly')
        self.zoom_choice.pack(side='right')
        self.zoom_choice.bind('<<ComboboxSelected>>', lambda _: self.set_zoom())
        ttk.Label(bar, text='Zoom').pack(side='right', padx=6)
        edits = ttk.Frame(frame)
        edits.pack(fill='x', pady=8)
        self.undo_button = ttk.Button(edits, text='Annuler', command=self.undo_mask)
        self.undo_button.pack(side='left')
        self.redo_button = ttk.Button(edits, text='Rétablir', command=self.redo_mask)
        self.redo_button.pack(side='left', padx=4)
        self.delete_button = ttk.Button(edits, text='Supprimer le masque', command=self.delete_mask)
        self.delete_button.pack(side='left')
        ttk.Label(edits, text='Glissez pour masquer. Cliquez un masque pour le sélectionner.').pack(side='left', padx=10)
        detection_bar = ttk.Frame(frame)
        detection_bar.pack(fill='x', pady=(0, 8))
        self.detect_button = ttk.Button(detection_bar, text='Relancer la détection',
                                        command=self.detect)
        self.detect_button.pack(side='left')
        self.review_button = ttk.Button(detection_bar, text='Vérifier les suggestions…', command=self.show_review)
        self.review_button.pack(side='left', padx=6)
        self.assurance_button = ttk.Button(detection_bar, text='Score et revue des risques…',
                                           command=self.show_assurance)
        self.assurance_button.pack(side='left')
        self.score_hint = tk.StringVar(value='Score de préparation : analyse requise • Aucune garantie d’anonymat')
        ttk.Label(frame, textvariable=self.score_hint, wraplength=1040).pack(anchor='w', pady=(0, 5))
        body = ttk.Frame(frame)
        body.pack(fill='both', expand=True)
        side = ttk.Frame(body)
        side.pack(side='left', fill='y', padx=(0, 10))
        ttk.Label(side, text='Pages • masques').pack(anchor='w', pady=(0, 5))
        self.page_list = tk.Listbox(side, width=16, bg='white', fg='#20342c',
            selectbackground='#235c47', selectforeground='white', font=('Segoe UI', 10),
            exportselection=False, activestyle='none', relief='flat')
        self.page_list.pack(fill='both', expand=True)
        self.page_list.bind('<<ListboxSelect>>', self.choose_page)
        viewport = ttk.Frame(body)
        viewport.pack(side='left', fill='both', expand=True)
        viewport.rowconfigure(0, weight=1)
        viewport.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewport, bg='#dce2dc', highlightthickness=0, cursor='crosshair')
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(viewport, orient='vertical', command=self.canvas.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(viewport, orient='horizontal', command=self.canvas.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        for event, function in {'<Configure>': self.schedule_draw, '<ButtonPress-1>': self.start,
            '<B1-Motion>': self.motion, '<ButtonRelease-1>': self.finish, '<MouseWheel>': self.wheel}.items():
            self.canvas.bind(event, function)
        self.canvas.bind('<Button-4>', lambda _: self.canvas.yview_scroll(-3, 'units'))
        self.canvas.bind('<Button-5>', lambda _: self.canvas.yview_scroll(3, 'units'))
        self.status = tk.StringVar(value='Ouvrez un PDF, un PNG, un JPEG ou un WebP statique.')
        ttk.Label(frame, textvariable=self.status, wraplength=1040).pack(anchor='w', pady=(8, 3))
        progress_row = ttk.Frame(frame)
        progress_row.pack(fill='x')
        self.progress = ttk.Progressbar(progress_row, mode='determinate')
        self.progress.pack(side='left', fill='x', expand=True)
        self.cancel_button = ttk.Button(progress_row, text='Annuler l’export', command=self.cancel_export)
        self.cancel_button.pack(side='right', padx=(8, 0))
        ttk.Label(frame, text='Le PDF exporté devient une copie en images : texte non sélectionnable, signature numérique perdue.',
            wraplength=1040).pack(anchor='w', pady=7)
        foot = ttk.Frame(frame)
        foot.pack(fill='x')
        ttk.Label(foot, text='Qualité PDF').pack(side='left')
        self.dpi = tk.StringVar(value='150')
        self.dpi_choice = ttk.Combobox(foot, textvariable=self.dpi, values=('72', '100', '150', '200'),
            width=5, state='readonly')
        self.dpi_choice.pack(side='left', padx=8)
        ttk.Label(foot, text='ppp • sans perte').pack(side='left')
        self.output_button = ttk.Button(foot, text='Ouvrir la copie', command=self.open_output)
        self.output_button.pack(side='right', padx=(8, 0))
        self.save = ttk.Button(foot, text='Exporter une copie…', command=self.export, style='Accent.TButton')
        self.save.pack(side='right')
        bindings = {'<Control-o>': self.open, '<Control-s>': self.export,
            '<Control-z>': self.undo_mask, '<Control-y>': self.redo_mask, '<Delete>': self.delete_mask,
            '<Prior>': lambda: self.move(-1), '<Next>': lambda: self.move(1),
            '<Control-plus>': lambda: self.zoom_step(1), '<Control-equal>': lambda: self.zoom_step(1),
            '<Control-minus>': lambda: self.zoom_step(-1), '<Control-0>': lambda: self.set_zoom(1),
            '<Escape>': self.escape}
        for key, function in bindings.items():
            root.bind(key, lambda event, fn=function: self.shortcut(event, fn))
        # On AZERTY, the physical 0 key reports "agrave" unless Shift is held.
        # Match the Windows virtual key as well as the layout-dependent keysym.
        root.bind('<Control-KeyPress>', self.platform_shortcut)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.controls()
        root.after(40, self.poll)
        if initial_path:
            root.after(80, lambda: self.load(initial_path))

    def shortcut(self, event, function):
        if event.widget.winfo_class() not in ('TCombobox', 'Entry', 'TEntry'):
            function()
            return 'break'

    def platform_shortcut(self, event):
        if sys.platform == 'win32' and event.keycode == 48:
            return self.shortcut(event, lambda: self.set_zoom(1))

    def controls(self):
        ready = bool(self.doc) and not self.busy
        flags = ((self.open_button, not self.busy), (self.prev, ready and self.page > 0),
            (self.next, ready and self.page + 1 < self.doc.pages),
            (self.undo_button, ready and bool(self.history)), (self.redo_button, ready and bool(self.future)),
            (self.delete_button, ready and any(b.page == self.page + 1 for b in self.all_boxes())),
            (self.detect_button, ready), (self.review_button, ready and self.report is not None),
            (self.assurance_button, ready),
            (self.save, ready), (self.cancel_button, self.busy in ('export', 'scan', 'audit_export')),
            (self.output_button, bool(self.last_output) and not self.busy and not self.dirty()))
        for button, enabled in flags:
            button.configure(state='normal' if enabled else 'disabled')
        self.page_list.configure(state='normal' if ready else 'disabled')
        self.zoom_choice.configure(state='readonly' if ready else 'disabled')
        self.dpi_choice.configure(state='readonly' if ready and self.doc.kind == 'pdf' else 'disabled')
        self.counter.configure(text=f'Page {self.page + 1} / {self.doc.pages}' if self.doc else 'Aucun document')
        self.cancel_button.configure(text='Annuler le contrôle' if self.busy == 'audit_export'
                                     else 'Annuler l’analyse' if self.busy == 'scan' else 'Annuler l’export')
        self.refresh_score()

    def begin(self, operation, **arguments):
        self.busy = operation
        self.pending = self.worker.submit(operation, **arguments)
        self.controls()

    def dirty(self):
        return self.mask_state() != self.exported

    def mask_state(self):
        return tuple(self.boxes), tuple(self.approved.items()), tuple(self.choices.items())

    def redaction_plan(self):
        from .methods import redaction_plan
        return redaction_plan(self.boxes, self.approved, self.choices)

    def all_boxes(self):
        return [*self.boxes, *(b for finding in self.approved.values() for b in finding.zones)]

    def detect(self):
        if self.doc and not self.busy and not self.closing:
            self.worker.cancel.clear()
            self.status.set('Analyse locale de toutes les pages : texte et OCR…')
            self.begin('scan', use_ocr=True)

    def show_review(self):
        if self.report is None:
            return
        if self.review:
            self.review.window.lift()
        else:
            from .review import ReviewWindow
            self.review = ReviewWindow(self)

    def show_finding(self, finding):
        if not self.busy:
            self.preview_finding = finding
            if self.page + 1 not in finding.pages:
                self.move(finding.pages[0] - 1 - self.page)
            else:
                self.draw()

    def approve_finding(self, finding, choice=None):
        if self.busy or (finding.id in self.approved and self.choices.get(finding.id) == choice):
            return
        from .methods import redaction_plan
        registry, choices = dict(self.approved), dict(self.choices)
        registry[finding.id] = finding
        if choice:
            choices[finding.id] = choice
        else:
            choices.pop(finding.id, None)
        redaction_plan(self.boxes, registry, choices)  # Validate before changing review state.
        self.remember()
        self.approved[finding.id] = finding
        self.choices = choices
        self.selected = None
        self.draw()
        self.refresh_status()
        if self.review:
            self.review.refresh()

    def revoke_finding(self, key):
        if self.busy or key not in self.approved:
            return
        self.remember()
        self.approved.pop(key)
        self.choices.pop(key, None)
        self.selected = None
        self.draw()
        self.refresh_status()
        if self.review:
            self.review.refresh()

    def find_name(self, value, *, exact=False):
        if self.report is not None and not self.busy:
            self.worker.cancel.clear()
            self.begin('find_term' if exact else 'find_name', value=value)

    def invalidate_assurance(self):
        self.criteria_snapshot, self.copy_snapshot, self.audit_snapshot = None, None, None

    def review_signature(self):
        return self.mask_state(), self.analysis_revision, self.purpose.strip(), self.audience

    def current_audit(self):
        if (self.audit is None or self.dirty() or self.audit_snapshot !=
                (self.mask_state(), self.analysis_revision)):
            return None
        try:
            stat = self.last_output.stat()
            stamp = stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
            return self.audit if stamp == self.audit.file_stamp else None
        except OSError:
            return None

    def get_preparation_score(self):
        from .assurance import preparation_score
        signature = self.review_signature()
        criteria = self.criteria_snapshot == signature
        copy = self.copy_snapshot == signature
        audit = self.current_audit()
        key = signature, criteria, copy, audit, self.report
        if self.score_cache is None or self.score_cache[0] != key:
            self.score_cache = key, preparation_score(self.report, self.all_boxes(),
                criteria_reviewed=criteria, copy_reviewed=copy, audit=audit, labels=self.redaction_plan()[1])
        return self.score_cache[1]

    def refresh_score(self):
        score = self.get_preparation_score()
        value = f'{score.value}/100' if score.value is not None else 'analyse requise'
        self.score_hint.set(f'Préparation à l’anonymisation : {value} • Indicateur interne, pas une garantie d’anonymat')
        if self.assurance_window:
            self.assurance_window.refresh()

    def show_assurance(self):
        if self.assurance_window:
            self.assurance_window.window.lift()
        else:
            from .assurance_ui import AssuranceWindow
            self.assurance_window = AssuranceWindow(self)

    def audit_copy(self):
        if self.last_output and not self.dirty() and not self.busy:
            self.worker.cancel.clear()
            self.audit, self.audit_snapshot, self.copy_snapshot = None, None, None
            self.pending_audit_snapshot = self.mask_state(), self.analysis_revision
            self.status.set('Contrôle local de la copie : structure, pixels et seconde lecture OCR…')
            self.begin('audit_export')

    def open(self):
        if self.busy:
            return
        if self.dirty() and not messagebox.askokcancel('Masques non exportés',
                'Ouvrir un autre fichier abandonnera les modifications non exportées. Continuer ?'):
            return
        path = filedialog.askopenfilename(filetypes=[('PDF et images', '*.pdf *.png *.jpg *.jpeg *.webp')])
        if path:
            self.load(path)

    def load(self, path):
        if not self.busy:
            self.status.set('Ouverture et préparation de l’aperçu…')
            self.begin('open', path=path)

    def move(self, delta):
        if not self.busy and self.doc and 0 <= self.page + delta < self.doc.pages:
            self.drag, self.selected = None, None
            self.render_page = self.page + delta
            self.status.set(f'Préparation de la page {self.render_page + 1}…')
            self.begin('render', page=self.render_page, dpi=self.preview_dpi)

    def choose_page(self, _):
        selection = self.page_list.curselection()
        if selection and selection[0] != self.page:
            self.move(selection[0] - self.page)

    def poll(self):
        try:
            while True:
                request, operation, status, payload = self.worker.results.get_nowait()
                if request != self.pending:
                    if status == 'ok' and operation == 'render':
                        payload.close()
                    continue
                if status == 'progress':
                    done, total = payload
                    self.progress.configure(maximum=total, value=done)
                    prefix = ('Analyse locale' if operation == 'scan' else
                              'Contrôle de la copie' if operation == 'audit_export' else 'Export')
                    self.status.set(f'{prefix} : page {done} / {total}' if done < total
                                    else ('Recherche des informations à vérifier…' if operation == 'scan'
                                          else 'Vérification et finalisation de la copie…'))
                    continue
                self.busy = None
                if status == 'error':
                    self.progress.configure(value=0)
                    self.status.set('Analyse annulée ; les validations précédentes sont conservées.'
                                    if operation == 'scan' and isinstance(payload, ExportCancelled)
                                    else str(payload))
                    if not self.closing and not isinstance(payload, ExportCancelled):
                        messagebox.showerror('Opération impossible', str(payload))
                elif operation in ('open', 'render'):
                    if self.preview:
                        self.preview.close()
                    if operation == 'open':
                        self.doc, self.preview = payload
                        self.boxes, self.history, self.future = [], [], []
                        self.approved = {}
                        self.choices = {}
                        self.exported = self.mask_state()
                        if self.review:
                            self.review.window.destroy()
                        self.report, self.review, self.preview_finding = None, None, None
                        self.analysis_revision += 1
                        self.invalidate_assurance()
                        self.audit = None
                        self.purpose, self.audience = '', ''
                        if self.assurance_window:
                            self.assurance_window.close()
                        self.page, self.zoom, self.preview_dpi = 0, 1.0, 90
                        self.zoom_value.set('Adapter')
                        self.visited, self.last_output = {0}, None
                        self.progress.configure(value=0)
                        self.root.title(f'Partage Clair {__version__} — {self.doc.name}')
                    else:
                        self.preview, self.page = payload, self.render_page
                        self.visited.add(self.page)
                    self.canvas.xview_moveto(0)
                    self.canvas.yview_moveto(0)
                    self.draw()
                    self.refresh_status()
                    if operation == 'open':
                        self.detect()
                elif operation == 'export':
                    self.last_output, self.exported = payload, self.mask_state()
                    self.audit, self.audit_snapshot, self.copy_snapshot = None, None, None
                    self.status.set('Copie créée. Ouvrez-la et vérifiez toutes les pages avant de partager.')
                elif operation == 'audit_export':
                    self.audit, self.audit_snapshot = payload, self.pending_audit_snapshot
                    self.status.set('Contrôle terminé : consultez le score, les avertissements et relisez la copie.')
                elif operation == 'scan':
                    self.analysis_revision += 1
                    self.invalidate_assurance()
                    self.report = payload
                    # Existing validations keep their complete geometry after a rescan.
                    registry = {f.id: f for f in payload.findings}
                    self.approved = {key: registry[key] for key in self.approved if key in registry}
                    if self.review:
                        self.review.refresh()
                    self.show_review()
                    self.status.set(f'{len(payload.findings)} groupe(s) proposé(s). Aucun nouveau masque appliqué.')
                elif operation in ('find_name', 'find_term'):
                    self.analysis_revision += 1
                    self.invalidate_assurance()
                    from .detection import ScanReport
                    findings = {f.id: f for f in self.report.findings}
                    findings[payload.id] = payload
                    self.report = ScanReport(tuple(findings.values()), self.report.warnings,
                                             self.report.pages, self.report.ocr_pages)
                    if self.review:
                        self.review.refresh()
                        self.review.tree.selection_set(payload.id)
                    self.status.set(f'{len(payload.zones)} zone(s) trouvée(s) : validation requise.')
                self.controls()
        except Empty:
            pass
        if self.closing and not self.worker.thread.is_alive():
            if self.preview:
                self.preview.close()
            self.root.destroy()
            return
        self.root.after(40, self.poll)

    def refresh_status(self):
        if self.doc:
            self.status.set(f'{len(self.all_boxes())} masque(s) • {len(self.approved)} groupe(s) validé(s) partout'
                            f' • {len(self.visited)} / {self.doc.pages} pages consultées'
                            + (' • Modifications à exporter' if self.dirty()
                               else ' • Métadonnées retirées à l’export'))
            self.controls()

    def schedule_draw(self, _=None):
        self.drag = None
        if self.redraw_after:
            self.root.after_cancel(self.redraw_after)
        self.redraw_after = self.root.after(70, self.draw)

    def draw(self):
        self.redraw_after = None
        self.canvas.delete('all')
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if not self.preview:
            self.canvas.create_text(cw / 2, ch / 2,
                text='Votre document reste sur cet ordinateur.\n\nOuvrez un fichier pour commencer.',
                fill='#50655a', font=('Segoe UI', 14), justify='center')
            return
        if cw < 30 or ch < 30:
            return
        pw, ph = self.preview.size
        scale = min((cw - 24) / pw, (ch - 24) / ph) * self.zoom
        scale = min(scale, math.sqrt(8_000_000 / (pw * ph)))
        w, h = max(1, round(pw * scale)), max(1, round(ph * scale))
        image = self.preview.resize((w, h), Image.Resampling.LANCZOS)
        x, y = max(12, (cw - w) / 2), max(12, (ch - h) / 2)
        self.area = x, y, w, h
        self.photo = ImageTk.PhotoImage(image)
        image.close()
        self.canvas.configure(scrollregion=(0, 0, max(cw, w + 24), max(ch, h + 24)))
        self.canvas.create_image(x, y, image=self.photo, anchor='nw')
        for index, box in enumerate(self.all_boxes()):
            if box.page == self.page + 1:
                self.canvas.create_rectangle(x + box.x0 * w, y + box.y0 * h,
                    x + box.x1 * w, y + box.y1 * h, fill='black',
                    outline='#d96b2b' if index == self.selected else 'black',
                    width=2 if index == self.selected else 1)
        from .core import DocumentError, label_bounds, label_patch
        self.label_photos = []
        for label in self.redaction_plan()[1]:
            if label.box.page == self.page + 1:
                left, top, right, bottom = label_bounds(label.box, (w, h))
                try:
                    patch = label_patch((right - left, bottom - top), label.text)
                except DocumentError:
                    continue  # Zoom in to read a label too small at the fit-page scale.
                try:
                    photo = ImageTk.PhotoImage(patch)
                finally:
                    patch.close()
                self.label_photos.append(photo)
                self.canvas.create_image(x + left, y + top, image=photo, anchor='nw')
        if self.preview_finding and self.preview_finding.id not in self.approved:
            for box in self.preview_finding.zones:
                if box.page == self.page + 1:
                    self.canvas.create_rectangle(x + box.x0 * w, y + box.y0 * h,
                        x + box.x1 * w, y + box.y1 * h, outline='#d96b2b', width=3, dash=(5, 3))
        self.page_list.configure(state='normal')
        self.page_list.delete(0, 'end')
        for index in range(self.doc.pages):
            count = sum(b.page == index + 1 for b in self.all_boxes())
            self.page_list.insert('end', f'{"✓" if index in self.visited else "·"} Page {index + 1}   ({count})')
        self.page_list.selection_set(self.page)
        self.page_list.see(self.page)
        self.controls()

    def set_zoom(self, value=None):
        if self.busy or not self.doc:
            return
        if value is None:
            value = 1 if self.zoom_value.get() == 'Adapter' else float(self.zoom_value.get().split()[0]) / 100
        self.zoom = max(1, min(4, value))
        self.zoom_value.set('Adapter' if self.zoom == 1 else f'{round(self.zoom * 100)} %')
        desired = min(200, max(90, round(90 * self.zoom)))
        if desired != self.preview_dpi:
            self.preview_dpi, self.render_page = desired, self.page
            self.begin('render', page=self.page, dpi=desired)
        else:
            self.draw()

    def zoom_step(self, delta):
        self.set_zoom(self.zoom + delta * .25)

    def wheel(self, event):
        if event.state & 0x4:
            self.zoom_step(1 if event.delta > 0 else -1)
        else:
            count = max(1, abs(event.delta) // 120)
            self.canvas.yview_scroll(-count if event.delta > 0 else count, 'units')
        return 'break'

    def point(self, event):
        x, y, w, h = self.area
        return (max(0, min(1, (self.canvas.canvasx(event.x) - x) / w)),
                max(0, min(1, (self.canvas.canvasy(event.y) - y) / h)))

    def start(self, event):
        if self.busy or not self.doc:
            return
        self.canvas.focus_set()
        x, y, w, h = self.area
        px, py = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if not (x <= px <= x + w and y <= py <= y + h):
            return
        point = self.point(event)
        boxes = self.all_boxes()
        for index in reversed(range(len(boxes))):
            box = boxes[index]
            if box.page == self.page + 1 and box.x0 <= point[0] <= box.x1 and box.y0 <= point[1] <= box.y1:
                self.selected = index
                self.draw()
                return
        self.selected, self.drag = None, point

    def motion(self, event):
        self.canvas.delete('drag')
        if self.drag:
            px, py = self.point(event)
            x, y, w, h = self.area
            self.canvas.create_rectangle(x + self.drag[0] * w, y + self.drag[1] * h,
                x + px * w, y + py * h, outline='#d96b2b', width=2, fill='black', tags='drag')

    def remember(self):
        self.invalidate_assurance()
        self.history.append(self.mask_state())
        self.future.clear()

    def restore_masks(self, state):
        self.invalidate_assurance()
        boxes, groups, choices = state
        self.boxes, self.approved, self.choices = list(boxes), dict(groups), dict(choices)
        if self.review:
            self.review.refresh()

    def finish(self, event):
        if not self.drag or self.busy:
            return
        px, py = self.point(event)
        x0, x1 = sorted((self.drag[0], px))
        y0, y1 = sorted((self.drag[1], py))
        self.drag = None
        if (x1 - x0) * self.area[2] >= 2 and (y1 - y0) * self.area[3] >= 2:
            self.remember()
            self.boxes.append(Box(self.page + 1, x0, y0, x1, y1))
            self.selected = len(self.boxes) - 1
        self.draw()
        self.refresh_status()

    def undo_mask(self):
        if not self.busy and self.history:
            self.future.append(self.mask_state())
            self.restore_masks(self.history.pop())
            self.selected = None
            self.draw()
            self.refresh_status()

    def redo_mask(self):
        if not self.busy and self.future:
            self.history.append(self.mask_state())
            self.restore_masks(self.future.pop())
            self.selected = None
            self.draw()
            self.refresh_status()

    def delete_mask(self):
        if self.busy:
            return
        index = self.selected
        if index is None:
            boxes = self.all_boxes()
            index = next((i for i in reversed(range(len(boxes)))
                          if boxes[i].page == self.page + 1), None)
        if index is not None:
            if index >= len(self.boxes):
                offset = index - len(self.boxes)
                for key, finding in self.approved.items():
                    if offset < len(finding.zones):
                        if messagebox.askokcancel('Validation groupée',
                                f'Retirer la validation de « {finding.value} » sur toutes les pages ?'):
                            self.revoke_finding(key)
                        return
                    offset -= len(finding.zones)
            self.remember()
            self.boxes.pop(index)
            self.selected = None
            self.draw()
            self.refresh_status()

    def escape(self):
        self.drag, self.selected = None, None
        self.draw()

    def export(self):
        if self.busy or not self.doc:
            return
        unvisited = self.doc.pages - len(self.visited)
        warning = f'{unvisited} page(s) non consultée(s).\n\n' if unvisited else ''
        retained = ('Des valeurs généralisées ou pseudonymes seront conservés dans la copie.\n\n'
                    if self.choices else '')
        if not messagebox.askokcancel('Vérifier avant de partager', warning +
                f'{len(self.all_boxes())} masque(s), {len(self.approved)} groupe(s) validé(s) partout.\n\n'
                + retained + 'Seules les suggestions validées et les masques manuels seront appliqués. '
                'La détection peut manquer des informations. Vérifiez aussi les photos, QR et codes-barres.'):
            return
        ext = '.pdf' if self.doc.kind == 'pdf' else '.png'
        target = filedialog.asksaveasfilename(initialfile=f'document-a-partager{ext}',
            defaultextension=ext, filetypes=[('Copie de partage', f'*{ext}')])
        if target:
            self.drag = None
            self.worker.cancel.clear()
            self.progress.configure(value=0)
            self.status.set('Export local en cours…')
            self.begin('export', target=Path(target), boxes=list(self.boxes),
                       groups=list(self.approved), choices=dict(self.choices), dpi=int(self.dpi.get()))

    def cancel_export(self):
        if self.busy in ('export', 'scan', 'audit_export'):
            self.worker.cancel.set()
            self.cancel_button.configure(state='disabled')
            self.status.set('Annulation demandée ; la page en cours doit finir de se traiter…')

    def open_output(self):
        if self.last_output and not self.busy:
            try:
                if sys.platform == 'win32':
                    os.startfile(self.last_output)
                else:
                    subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(self.last_output)])
            except OSError as error:
                messagebox.showerror('Ouverture impossible', str(error))

    def close(self):
        if self.closing:
            return
        if self.dirty() and not messagebox.askokcancel('Masques non exportés',
                'Les modifications de masques non exportées seront perdues. Fermer ?'):
            return
        self.closing, self.busy = True, 'closing'
        self.controls()
        self.status.set('Fermeture et nettoyage du traitement en cours…')
        self.worker.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Partage Clair — interface locale')
    parser.add_argument('source', nargs='?', type=Path, help='Document à ouvrir au démarrage')
    args = parser.parse_args(argv)
    root = tk.Tk()
    App(root, args.source)
    root.mainloop()


if __name__ == '__main__':
    main()
