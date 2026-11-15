"""A local batch review: select masks, inspect pages, explicitly approve each file."""

import math
import os
import subprocess
import sys
import tkinter as tk
from dataclasses import replace
from queue import Empty
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .batch import MAX_FILES, BatchWorker
from .core import Box, DocumentError, ExportCancelled
from .profiles import PROFILES


class BatchWindow:
    batch_controller = True
    doc = None  # Settings must not trigger a single-document scan.

    def __init__(self, app):
        self.app = app
        self.window = self.root = tk.Toplevel(app.root)
        self.window.title('Traitement par lots — vérifier avant de masquer')
        self.window.geometry('1320x850')
        self.window.minsize(1080, 740)
        self.window.transient(app.root)
        self.window.grab_set()
        self.worker = BatchWorker()
        self.detection_options = replace(app.detection_options, mode='rules')
        self.detection_window = None
        self.files, self.jobs = (), {}
        self.current, self.pending, self.busy = None, None, None
        self.preview, self.photo, self.drag = None, None, None
        self.page, self.closing, self.poll_after = 1, False, None
        self.area = (0, 0, 1, 1)
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Traitement par lots : analyser, vérifier, valider',
                  font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        self.scope = tk.StringVar()
        ttk.Label(frame, textvariable=self.scope, wraplength=1250).pack(anchor='w', pady=6)
        top = ttk.Frame(frame)
        top.pack(fill='x')
        self.files_button = ttk.Button(top, text='Choisir les documents…', command=self.choose_files)
        self.files_button.pack(side='left')
        self.settings_button = ttk.Button(top, text='Mode, listes et profil…', command=self.settings)
        self.settings_button.pack(side='left', padx=6)
        self.analyze_button = ttk.Button(top, text='Analyser le lot', command=self.analyze)
        self.analyze_button.pack(side='left')
        self.cancel_button = ttk.Button(top, text='Annuler le traitement', command=self.cancel)
        self.cancel_button.pack(side='right')
        panes = ttk.Panedwindow(frame, orient='horizontal')
        panes.pack(fill='both', expand=True, pady=10)
        left, center, right = (ttk.Frame(panes, padding=5) for _ in range(3))
        panes.add(left, weight=1)
        panes.add(center, weight=3)
        panes.add(right, weight=2)
        ttk.Label(left, text='Documents et état').pack(anchor='w')
        self.documents = ttk.Treeview(left, columns=('name', 'status'), show='headings', selectmode='browse')
        self.documents.heading('name', text='Document')
        self.documents.heading('status', text='État')
        self.documents.column('name', width=130, minwidth=80)
        self.documents.column('status', width=150, minwidth=90)
        scrollbar = ttk.Scrollbar(left, command=self.documents.yview)
        self.documents.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.documents.pack(fill='both', expand=True)
        self.documents.bind('<<TreeviewSelect>>', lambda _: self.select_document())
        navigation = ttk.Frame(center)
        navigation.pack(fill='x')
        self.previous = ttk.Button(navigation, text='←', command=lambda: self.move(-1))
        self.previous.pack(side='left')
        self.page_hint = tk.StringVar(value='Choisissez un document analysé')
        ttk.Label(navigation, textvariable=self.page_hint).pack(side='left', padx=6)
        self.next = ttk.Button(navigation, text='→', command=lambda: self.move(1))
        self.next.pack(side='left')
        self.zoom = tk.StringVar(value='Adapter')
        zoom = ttk.Combobox(navigation, textvariable=self.zoom, values=('Adapter', '150 %', '200 %', '300 %'),
                            state='readonly', width=8)
        zoom.pack(side='right')
        zoom.bind('<<ComboboxSelected>>', lambda _: self.draw())
        viewport = ttk.Frame(center)
        viewport.pack(fill='both', expand=True, pady=6)
        viewport.rowconfigure(0, weight=1)
        viewport.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewport, bg='#dce2dc', highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(viewport, orient='vertical', command=self.canvas.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(viewport, orient='horizontal', command=self.canvas.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        for event, function in (('<Configure>', lambda _: self.draw()), ('<ButtonPress-1>', self.start_box),
                                ('<B1-Motion>', self.motion_box), ('<ButtonRelease-1>', self.finish_box)):
            self.canvas.bind(event, function)
        ttk.Label(center, text='Glissez sur la page pour ajouter un masque manuel.', wraplength=470).pack(anchor='w')
        self.undo_button = ttk.Button(center, text='Retirer le dernier rectangle manuel', command=lambda: self.action('undo_box'))
        self.undo_button.pack(anchor='w', pady=4)
        self.page_button = ttk.Button(center, text='Cette page a été vérifiée', command=lambda: self.action('review_page', page=self.page))
        self.page_button.pack(anchor='w')
        ttk.Label(right, text='Propositions : aucune n’est masquée au départ.').pack(anchor='w')
        self.findings = ttk.Treeview(right, columns=('kind', 'value', 'pages', 'state'), show='headings', selectmode='extended')
        for key, label, width in (('kind', 'Type', 100), ('value', 'Information', 145), ('pages', 'Pages', 55), ('state', 'État', 80)):
            self.findings.heading(key, text=label)
            self.findings.column(key, width=width, minwidth=50)
        self.findings.pack(fill='both', expand=True, pady=6)
        self.findings.bind('<<TreeviewSelect>>', lambda _: self.draw())
        ttk.Button(right, text='Tout sélectionner (sans masquer)', command=lambda: self.findings.selection_set(
            self.findings.get_children())).pack(anchor='w')
        actions = ttk.Frame(right)
        actions.pack(fill='x', pady=6)
        self.accept_button = ttk.Button(actions, text='Valider la sélection', command=lambda: self.candidates(True))
        self.accept_button.pack(side='left')
        self.revoke_button = ttk.Button(actions, text='Retirer les masques', command=lambda: self.candidates(False))
        self.revoke_button.pack(side='left', padx=4)
        self.detail = tk.StringVar(value='Vérifiez chaque page, y compris images, signatures et tableaux.')
        ttk.Label(right, textvariable=self.detail, wraplength=390).pack(anchor='w', pady=6)
        self.approve_button = ttk.Button(right, text='Valider ce document pour export',
                                         command=lambda: self.action('approve_document'), style='Accent.TButton')
        self.approve_button.pack(anchor='w', pady=6)
        foot = ttk.Frame(frame)
        foot.pack(fill='x')
        self.status = tk.StringVar(value='1. Chargez les listes et le profil. 2. Choisissez les fichiers. 3. Analysez et vérifiez.')
        ttk.Label(foot, textvariable=self.status, wraplength=900).pack(side='left')
        self.export_button = ttk.Button(foot, text='Exporter les documents validés…', command=self.export,
                                        style='Accent.TButton')
        self.export_button.pack(side='right')
        self.output_button = ttk.Button(frame, text='Ouvrir la copie du document sélectionné', command=self.open_output)
        self.output_button.pack(anchor='e', pady=5)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.controls()
        self.poll_after = self.app.root.after(40, self.poll)

    def job(self):
        return self.jobs.get(self.current)

    def controls(self):
        job = self.job()
        ready = not self.busy and job is not None and job.report is not None and not self.closing
        mode = 'Sans IA : OCR et modèle désactivés' if self.detection_options.mode == 'rules' else 'Assisté local : OCR et modèle activés'
        self.scope.set(f'{mode} • Profil {PROFILES[self.detection_options.profile]} • '
                       f'{len(self.detection_options.references)} informations de listes • '
                       'Masquage complet uniquement')
        for widget, enabled in ((self.files_button, not self.busy), (self.settings_button, not self.busy and not self.jobs),
                (self.analyze_button, not self.busy and bool(self.files)), (self.cancel_button, bool(self.busy)),
                (self.previous, ready and self.page > 1), (self.next, ready and self.page < job.pages),
                (self.page_button, ready and self.preview is not None), (self.undo_button, ready and bool(job.boxes)),
                (self.accept_button, ready), (self.revoke_button, ready),
                (self.approve_button, ready and len(job.reviewed) == job.pages and not job.ready),
                (self.export_button, not self.busy and any(j.ready and j.output is None for j in self.jobs.values())),
                (self.output_button, not self.busy and job is not None and job.output is not None)):
            widget.configure(state='normal' if enabled and not self.closing else 'disabled')
        if job and job.report:
            self.page_hint.set(f'Page {self.page}/{job.pages} • {len(job.reviewed)} vérifiée(s)')
            self.detail.set(f'{len(job.approved)} groupe(s) masqué(s), {len(job.boxes)} rectangle(s). '
                            f'{len(job.reviewed)}/{job.pages} pages vérifiées. '
                            + ' '.join(job.report.warnings) + '\nLa copie exportée devra aussi être relue.')

    def begin(self, operation, **arguments):
        if self.busy or self.closing:
            return
        self.worker.cancel.clear()
        self.busy = operation
        self.pending = self.worker.submit(operation, **arguments)
        self.controls()

    def settings(self):
        if self.busy or self.jobs:
            return
        from .detection_ui import DetectionWindow
        if not self.detection_window:
            self.detection_window = DetectionWindow(self)
            self.detection_window.window.grab_set()

    def set_detection_options(self, options):
        if self.busy or self.jobs:
            raise DocumentError('Choisissez les règles avant d’analyser le lot, ou rechargez ses fichiers.')
        self.detection_options = options
        self.controls()

    def import_references(self, path, source):
        self.begin('import_references', path=path, source=source)

    def choose_files(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(parent=self.window, filetypes=[('PDF et images', '*.pdf *.png *.jpg *.jpeg *.webp')])
        if not paths:
            return
        if len(paths) > MAX_FILES:
            messagebox.showinfo('Lot limité', 'Choisissez au maximum 100 documents.', parent=self.window)
            return
        if self.jobs and not messagebox.askokcancel('Changer de lot',
                'Les vérifications et masques de ce lot seront abandonnés. Continuer ?', parent=self.window):
            return
        self.files, self.jobs, self.current = paths, {}, None
        self.clear_preview()
        self.refresh()
        self.status.set(f'{len(paths)} document(s) sélectionné(s). Configurez les listes puis analysez.')
        self.begin('clear')

    def analyze(self):
        if self.busy or not self.files:
            return
        if self.jobs and not messagebox.askokcancel('Réanalyser',
                'La réanalyse effacera les validations de ce lot. Continuer ?', parent=self.window):
            return
        self.jobs, self.current = {}, None
        self.clear_preview()
        self.refresh()
        self.begin('analyze', paths=self.files, options=self.detection_options)

    def refresh(self):
        for key in self.documents.get_children():
            if key not in self.jobs:
                self.documents.delete(key)
        for job in self.jobs.values():
            values = job.path.name, job.status
            if self.documents.exists(job.id):
                self.documents.item(job.id, values=values)
            else:
                self.documents.insert('', 'end', iid=job.id, values=values)
        selection = self.findings.selection()
        self.findings.delete(*self.findings.get_children())
        job = self.job()
        if job and job.report:
            for finding in job.report.findings:
                self.findings.insert('', 'end', iid=finding.id,
                    values=(finding.kind, finding.value, ', '.join(map(str, finding.pages)),
                            'Masqué' if finding.id in job.approved else 'À vérifier'))
            self.findings.selection_set([key for key in selection if self.findings.exists(key)])
        self.controls()

    def select_document(self):
        if self.busy:
            return
        selected = self.documents.selection()
        if not selected or selected[0] == self.current:
            return
        self.current, self.page = selected[0], 1
        self.clear_preview()
        self.refresh()
        if self.job().report:
            self.begin('render', key=self.current, page=self.page)

    def move(self, delta):
        job = self.job()
        if not self.busy and job and 1 <= self.page + delta <= job.pages:
            self.page += delta
            self.clear_preview()
            self.begin('render', key=self.current, page=self.page)

    def clear_preview(self):
        if self.preview:
            self.preview.close()
        self.preview, self.photo = None, None
        self.canvas.delete('all')

    def draw(self):
        self.canvas.delete('all')
        job = self.job()
        if not self.preview or job is None or job.report is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if min(cw, ch) < 30:
            return
        pw, ph = self.preview.size
        zoom = 1 if self.zoom.get() == 'Adapter' else int(self.zoom.get().split()[0]) / 100
        scale = min((cw - 24) / pw, (ch - 24) / ph) * zoom
        scale = min(scale, math.sqrt(8_000_000 / (pw * ph)))
        w, h = max(1, round(pw * scale)), max(1, round(ph * scale))
        resized = self.preview.resize((w, h), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(resized)
        resized.close()
        x, y = max(12, (cw - w) / 2), max(12, (ch - h) / 2)
        self.area = x, y, w, h
        self.canvas.configure(scrollregion=(0, 0, max(cw, w + 24), max(ch, h + 24)))
        self.canvas.create_image(x, y, anchor='nw', image=self.photo)
        for box in job.masks:
            if box.page == self.page:
                self.canvas.create_rectangle(x + box.x0 * w, y + box.y0 * h, x + box.x1 * w, y + box.y1 * h,
                                             fill='black', outline='black')
        selected = set(self.findings.selection())
        for finding in job.report.findings:
            if finding.id in selected:
                for box in finding.zones:
                    if box.page == self.page:
                        self.canvas.create_rectangle(x + box.x0 * w, y + box.y0 * h, x + box.x1 * w,
                            y + box.y1 * h, outline='#d48a22', width=2, dash=(5, 3))

    def point(self, event):
        x, y, w, h = self.area
        return max(0, min(1, (self.canvas.canvasx(event.x) - x) / w)), max(0, min(1, (self.canvas.canvasy(event.y) - y) / h))

    def start_box(self, event):
        if not self.busy and self.preview:
            self.drag = self.point(event)

    def motion_box(self, event):
        if self.drag:
            x, y, w, h = self.area
            end = self.point(event)
            self.canvas.delete('drag')
            self.canvas.create_rectangle(x + self.drag[0] * w, y + self.drag[1] * h,
                x + end[0] * w, y + end[1] * h, outline='#235c47', width=2, tags='drag')

    def finish_box(self, event):
        if self.drag and not self.busy:
            start, end = self.drag, self.point(event)
            self.drag = None
            if abs(start[0] - end[0]) * self.area[2] >= 3 and abs(start[1] - end[1]) * self.area[3] >= 3:
                self.action('add_box', box=Box(self.page, min(start[0], end[0]), min(start[1], end[1]),
                                              max(start[0], end[0]), max(start[1], end[1])))

    def action(self, operation, **arguments):
        if not self.busy and self.job() and self.job().report:
            self.begin(operation, key=self.current, **arguments)

    def candidates(self, approve):
        if self.findings.selection():
            self.action('candidates', identifiers=self.findings.selection(), approve=approve)

    def export(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(parent=self.window, title='Destination des copies validées')
        if folder:
            self.begin('export', folder=folder)

    def cancel(self):
        if self.busy:
            self.worker.cancel.set()
            self.status.set('Annulation demandée ; les copies déjà terminées sont conservées.')

    def open_output(self):
        job = self.job()
        if job and job.output and not self.busy:
            if sys.platform == 'win32':
                os.startfile(job.output)
            else:
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(job.output)])

    def poll(self):
        self.poll_after = None
        try:
            while True:
                request, operation, status, payload = self.worker.results.get_nowait()
                if request != self.pending:
                    if operation == 'render' and status == 'ok':
                        payload.close()
                    continue
                if status == 'progress':
                    done, total, job = payload
                    self.jobs[job.id] = job
                    self.status.set(f'{"Analyse" if operation == "analyze" else "Export"} : {done}/{total} document(s).')
                    self.refresh()
                    continue
                self.busy = None
                if status == 'error':
                    if operation != 'import_references':
                        self.jobs = dict(self.worker.session.jobs)
                    self.status.set('Traitement annulé ; vérifiez les états et copies déjà créées.'
                                    if isinstance(payload, ExportCancelled) else str(payload))
                    if not self.closing and not isinstance(payload, ExportCancelled):
                        messagebox.showerror('Lot : opération impossible', str(payload), parent=self.window)
                elif operation == 'render':
                    self.clear_preview()
                    self.preview = payload
                elif operation in ('analyze', 'export'):
                    self.jobs = {job.id: job for job in payload}
                    self.status.set('Analyse terminée : choisissez les zones, vérifiez chaque page et validez les documents.'
                                    if operation == 'analyze' else 'Export terminé : relisez chaque copie ; les documents non validés ont été ignorés.')
                elif operation == 'import_references':
                    if self.detection_window:
                        self.detection_window.receive_entries(*payload)
                elif operation == 'clear':
                    self.jobs = {}
                else:
                    self.jobs[payload.id] = payload
                self.refresh()
                self.draw()
        except Empty:
            pass
        if self.closing and not self.worker.thread.is_alive():
            self.clear_preview()
            self.app.batch_window = None
            self.window.destroy()
            return
        self.poll_after = self.app.root.after(40, self.poll)

    def close(self):
        if self.closing:
            return
        if any(j.output is None and (j.approved or j.boxes or j.reviewed) for j in self.jobs.values()) and not messagebox.askokcancel(
                'Lot non exporté', 'Les validations non exportées seront perdues. Fermer ?', parent=self.window):
            return
        if self.detection_window:
            self.detection_window.close()
        self.closing = True
        self.worker.stop()
        self.controls()
