"""Review-only local suggestions; validation is an explicit group action."""

import tkinter as tk
from tkinter import messagebox, ttk


class ReviewWindow:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Vérifier les informations sensibles — traitement local')
        self.window.geometry('1000x590')
        self.window.minsize(900, 650)
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
        methods = ttk.Frame(frame)
        methods.pack(fill='x', pady=(8, 0))
        ttk.Label(methods, text='Méthode :').pack(side='left')
        self.method = tk.StringVar(value='Masquer entièrement')
        self.method_choice = ttk.Combobox(methods, textvariable=self.method, state='readonly', width=25,
            values=('Masquer entièrement', 'Réduire la précision', 'Remplacer par un pseudonyme'))
        self.method_choice.pack(side='left', padx=6)
        self.method_choice.bind('<<ComboboxSelected>>', lambda _: self.method_detail())
        self.alias = ttk.Entry(methods, width=22)
        self.alias.insert(0, 'Personne A')
        self.alias.configure(state='disabled')
        self.alias.pack(side='left')
        ttk.Label(frame, text='Réduire : date → année, âge → tranche de 10 ans, montant → tranche de 1 000. '
                  'Un pseudonyme reste recoupable ; les deux méthodes conservent un score prudent.',
                  wraplength=900).pack(anchor='w', pady=(4, 0))
        custom = ttk.Frame(frame)
        custom.pack(fill='x', pady=(12, 0))
        ttk.Label(custom, text='Nom ou détail oublié :').pack(side='left')
        self.name = ttk.Entry(custom)
        self.name.pack(side='left', fill='x', expand=True, padx=8)
        ttk.Button(custom, text='Chercher partout', command=self.search_name).pack(side='left')
        self.name.bind('<Return>', lambda _: self.search_name())
        self.exact = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Rechercher ce texte exact (lieu, organisme, détail contextuel) '
                        'plutôt que les composants d’un nom', variable=self.exact).pack(anchor='w', pady=(4, 0))
        self.coverage = tk.StringVar()
        ttk.Label(frame, textvariable=self.coverage, wraplength=900).pack(anchor='w', pady=(8, 0))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()

    def refresh(self):
        selection = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for finding in self.app.report.findings:
            pages = ', '.join(map(str, finding.pages))
            choice = self.app.choices.get(finding.id)
            state = ('Généralisé' if choice and choice.method == 'generalise' else
                     'Pseudonyme' if choice else 'Validé partout') if finding.id in self.app.approved else 'À vérifier'
            self.tree.insert('', 'end', iid=finding.id,
                values=(finding.kind, finding.value, len(finding.zones), pages, state))
        if selection and self.tree.exists(selection[0]):
            self.tree.selection_set(selection[0])
        report = self.app.report
        warning = ' '.join(report.warnings)
        from .detection_options import ALL_CATEGORIES
        scope = ('Toutes les catégories.' if report.categories == ALL_CATEGORIES else
                 f'Analyse partielle : {len(report.categories)}/{len(ALL_CATEGORIES)} catégories. '
                 'Les masques déjà validés restent conservés.')
        context = (f'Contexte : {report.ner_pages}/{report.pages} pages.' if report.ner_requested
                   else 'Contexte non demandé pour ces catégories.')
        self.coverage.set(f'OCR : {report.ocr_pages}/{report.pages} pages. '
                          f'{context} {scope} {warning} La détection peut manquer des informations : relisez la copie.')
        if report.mode == 'rules':
            self.coverage.set(f'Sans IA : texte PDF sur {report.text_pages}/{report.pages} pages. '
                              f'OCR et modèle désactivés. {scope} {warning} Relisez toutes les pages.')

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
            choice = self.app.choices.get(finding.id)
            self.method.set('Réduire la précision' if choice and choice.method == 'generalise' else
                            'Remplacer par un pseudonyme' if choice else 'Masquer entièrement')
            if choice and choice.method == 'pseudonym':
                self.alias.configure(state='normal')
                self.alias.delete(0, 'end')
                self.alias.insert(0, choice.text)
            self.method_detail()

    def method_detail(self):
        from .methods import generalisation
        finding = self.chosen()
        self.alias.configure(state='normal' if self.method.get() == 'Remplacer par un pseudonyme' else 'disabled')
        if finding:
            self.validate.configure(text='Valider la généralisation partout' if self.method.get() == 'Réduire la précision'
                                    else 'Valider le pseudonyme partout' if self.method.get() == 'Remplacer par un pseudonyme'
                                    else 'Valider ce nom partout' if finding.kind == 'Nom' else 'Valider toutes les zones')
        if finding and self.method.get() == 'Réduire la précision':
            proposal = generalisation(finding)
            self.detail.set(f'Proposition : {proposal}' if proposal else
                            'Pas de généralisation fiable pour cette valeur ; choisissez le masquage complet.')

    def accept(self):
        finding = self.chosen()
        if finding:
            from .core import DocumentError
            from .methods import MethodChoice, generalisation
            choice = None
            try:
                if self.method.get() == 'Réduire la précision':
                    proposal = generalisation(finding)
                    if proposal is None:
                        raise DocumentError('Aucune généralisation fiable proposée. Choisissez le masquage complet.')
                    choice = MethodChoice('generalise', proposal)
                elif self.method.get() == 'Remplacer par un pseudonyme':
                    choice = MethodChoice('pseudonym', self.alias.get().strip())
                self.app.approve_finding(finding, choice)
            except DocumentError as error:
                messagebox.showinfo('Méthode à vérifier', str(error), parent=self.window)

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
            self.app.find_name(value, exact=self.exact.get())
        elif not value:
            messagebox.showinfo('Rechercher un nom', 'Saisissez le nom à rechercher dans tout le document.',
                                parent=self.window)

    def close(self):
        self.app.review = None
        self.app.preview_finding = None
        self.app.draw()
        self.window.destroy()
