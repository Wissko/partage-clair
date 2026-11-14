"""Review-only local suggestions; validation is an explicit group action."""

import tkinter as tk
from tkinter import messagebox, ttk


class ReviewWindow:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Vérifier les informations sensibles — traitement local')
        self.window.geometry('940x540')
        self.window.minsize(760, 430)
        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Aucune suggestion n’est masquée avant votre validation.',
                  font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Un nom validé couvre le nom complet, le prénom et le nom séparés, '
                  'dans toutes les pages analysées.', wraplength=900).pack(anchor='w', pady=(4, 10))
        area = ttk.Frame(frame)
        area.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(area, columns=('kind', 'value', 'zones', 'pages', 'state'),
                                show='headings', selectmode='browse')
        for key, label, width in (('kind', 'Type', 120), ('value', 'Information reconnue', 300),
                                  ('zones', 'Zones', 55), ('pages', 'Pages', 110),
                                  ('state', 'Validation', 100)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=45)
        scroll = ttk.Scrollbar(area, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.detail = tk.StringVar(value='Sélectionnez une information pour voir ses zones sur la page.')
        ttk.Label(frame, textvariable=self.detail, wraplength=900).pack(anchor='w', pady=8)
        preview = ttk.Frame(frame)
        preview.pack(fill='x', pady=(0, 8))
        ttk.Button(preview, text='Voir les zones sur la page', command=self.show_page).pack(side='left')
        ttk.Label(preview, text='Retour : « Vérifier les suggestions ».').pack(side='left', padx=8)
        ttk.Button(preview, text='Page suivante du groupe', command=self.next_page).pack(side='right')
        row = ttk.Frame(frame)
        row.pack(fill='x')
        self.validate = ttk.Button(row, text='Valider toutes les zones', command=self.accept,
                                   style='Accent.TButton')
        self.validate.pack(side='left')
        ttk.Button(row, text='Retirer cette validation partout', command=self.revoke).pack(side='left', padx=6)
        custom = ttk.Frame(frame)
        custom.pack(fill='x', pady=(12, 0))
        ttk.Label(custom, text='Nom oublié par la détection :').pack(side='left')
        self.name = ttk.Entry(custom)
        self.name.pack(side='left', fill='x', expand=True, padx=8)
        ttk.Button(custom, text='Chercher partout', command=self.search_name).pack(side='left')
        self.name.bind('<Return>', lambda _: self.search_name())
        self.coverage = tk.StringVar()
        ttk.Label(frame, textvariable=self.coverage, wraplength=900).pack(anchor='w', pady=(8, 0))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()

    def refresh(self):
        selection = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for finding in self.app.report.findings:
            pages = ', '.join(map(str, finding.pages))
            state = 'Validé partout' if finding.id in self.app.approved else 'À vérifier'
            self.tree.insert('', 'end', iid=finding.id,
                values=(finding.kind, finding.value, len(finding.zones), pages, state))
        if selection and self.tree.exists(selection[0]):
            self.tree.selection_set(selection[0])
        report = self.app.report
        warning = ' '.join(report.warnings)
        self.coverage.set(f'OCR : {report.ocr_pages}/{report.pages} pages. '
                          f'{warning} La détection peut manquer des informations : relisez la copie.')

    def chosen(self):
        selection = self.tree.selection()
        return next((f for f in self.app.report.findings if selection and f.id == selection[0]), None)

    def select(self, _=None):
        finding = self.chosen()
        if finding:
            terms = ', '.join(finding.terms) if finding.terms else finding.value
            self.detail.set(f'{finding.reason} • Formes couvertes : {terms}. '
                            f'{len(finding.zones)} zone(s), pages {", ".join(map(str, finding.pages))}.')
            self.validate.configure(text='Valider ce nom partout' if finding.kind == 'Nom'
                                    else 'Valider toutes les zones')
            self.app.show_finding(finding)

    def accept(self):
        finding = self.chosen()
        if finding:
            self.app.approve_finding(finding)

    def revoke(self):
        finding = self.chosen()
        if finding:
            self.app.revoke_finding(finding.id)

    def next_page(self):
        finding = self.chosen()
        if finding and not self.app.busy:
            following = next((p for p in finding.pages if p > self.app.page + 1), finding.pages[0])
            self.app.move(following - 1 - self.app.page)

    def show_page(self):
        finding = self.chosen()
        if finding and not self.app.busy:
            self.app.show_finding(finding)
            self.app.root.lift()
            self.app.root.focus_set()

    def search_name(self):
        value = self.name.get().strip()
        if value and not self.app.busy:
            self.app.find_name(value)
        elif not value:
            messagebox.showinfo('Rechercher un nom', 'Saisissez le nom à rechercher dans tout le document.',
                                parent=self.window)

    def close(self):
        self.app.review = None
        self.app.preview_finding = None
        self.app.draw()
        self.window.destroy()
