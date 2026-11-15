"""Human-selected scope and an in-memory confidential dictionary."""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .core import DocumentError
from .detection_options import CATEGORIES, DetectionOptions
from .profiles import PROFILES

MODES = {'Sans IA — règles et listes': 'rules', 'Assisté local — OCR et modèle': 'assisted'}


class DetectionWindow:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Choisir les données à détecter — en local')
        self.window.geometry('920x770')
        self.window.minsize(840, 700)
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Quelles données rechercher ?',
                  font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Tout est sélectionné au départ. Ces choix proposent des zones ; '
                  'seule votre validation les masque.', wraplength=780).pack(anchor='w', pady=(6, 10))
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=6)
        self.mode = tk.StringVar(value=next(k for k, v in MODES.items() if v == app.detection_options.mode))
        ttk.Label(controls, text='Mode').pack(side='left')
        self.mode_choice = ttk.Combobox(controls, state='readonly', textvariable=self.mode, width=32,
            values=tuple(k for k, v in MODES.items() if not getattr(app, 'strict_only', False) or v == 'rules'))
        self.mode_choice.pack(side='left', padx=6)
        self.profile = tk.StringVar(value=PROFILES[app.detection_options.profile])
        ttk.Label(controls, text='Profil').pack(side='left', padx=(12, 0))
        ttk.Combobox(controls, state='readonly', textvariable=self.profile, values=tuple(PROFILES.values()),
                     width=15).pack(side='left', padx=6)
        self.mode_help = tk.StringVar()
        self.mode_choice.bind('<<ComboboxSelected>>', lambda _: self.explain_mode())
        self.explain_mode()
        ttk.Label(frame, textvariable=self.mode_help, wraplength=860).pack(anchor='w', pady=6)
        outer = frame
        notebook = ttk.Notebook(outer)
        notebook.pack(fill='both', expand=True)
        frame, lists = ttk.Frame(notebook, padding=10), ttk.Frame(notebook, padding=12)
        notebook.add(frame, text='Catégories et expressions')
        notebook.add(lists, text='Listes clients et salariés')
        self.entries = app.detection_options.references
        self.list_counts = {}
        for source, label in (('clients', 'Clients'), ('employees', 'Salariés')):
            row = ttk.Frame(lists)
            row.pack(fill='x', pady=12)
            ttk.Button(row, text=f'Importer la liste {label.lower()} (CSV)…',
                       command=lambda s=source: self.import_list(s)).pack(side='left')
            ttk.Button(row, text='Retirer', command=lambda s=source: self.receive_entries(s, ())).pack(side='right')
            count = tk.StringVar()
            self.list_counts[source] = count
            ttk.Label(row, textvariable=count).pack(side='left', padx=12)
        self.update_counts()
        ttk.Label(lists, text='CSV avec en-têtes, séparateur point-virgule, virgule ou tabulation.\n\n'
                  'Exemples :\nprenom;nom;email;matricule\nentreprise;reference_client;iban\n\n'
                  'Une seule colonne « nom_complet » ou « entreprise » est aussi acceptée. '
                  '20 000 informations au total, fichier de 5 Mo maximum.\n\n'
                  'Les listes restent en mémoire pendant la session. Aucun envoi, aucune copie du CSV. '
                  'Les noms et leurs composants sont recherchés : vérifiez les homonymes et prénoms communs. '
                  'Sans IA, les noms inconnus de vos listes peuvent être manqués.',
                  wraplength=810).pack(anchor='w', pady=16)
        grid = ttk.Frame(frame)
        grid.pack(fill='x')
        self.variables = {}
        for i, (key, label) in enumerate(CATEGORIES):
            variable = tk.BooleanVar(value=key in app.detection_options.categories)
            self.variables[key] = variable
            ttk.Checkbutton(grid, text=label, variable=variable).grid(
                row=i // 2, column=i % 2, sticky='w', padx=(0, 12), pady=4)
        ttk.Button(frame, text='Tout sélectionner', command=self.select_all).pack(anchor='w', pady=8)
        ttk.Label(frame, text='Expressions confidentielles : une par ligne (200 maximum)',
                  font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Exemples : client, projet interne, produit, code, clause confidentielle. '
                  'Recherche de l’expression entière sur toutes les pages, sans couper ses mots.',
                  wraplength=780).pack(anchor='w', pady=(4, 6))
        self.terms = ScrolledText(frame, height=6, wrap='word', font=('Segoe UI', 10))
        self.terms.pack(fill='both', expand=True)
        self.terms.insert('1.0', '\n'.join(app.detection_options.terms))
        ttk.Label(frame, text='Ces expressions restent en mémoire pour la session et les prochains documents. '
                  'Elles ne sont ni envoyées ni enregistrées par l’application. '
                  'Les règles métier ne reconnaissent pas tous les secrets ; relisez la copie avant un LLM.',
                  wraplength=780).pack(anchor='w', pady=8)
        row = ttk.Frame(outer)
        row.pack(fill='x')
        ttk.Button(row, text='Annuler', command=self.close).pack(side='right')
        self.apply_button = ttk.Button(row, text='Appliquer et analyser' if app.doc else 'Appliquer',
                                       command=self.apply, style='Accent.TButton')
        self.apply_button.pack(side='right', padx=8)
        self.window.protocol('WM_DELETE_WINDOW', self.close)

    def select_all(self):
        for variable in self.variables.values():
            variable.set(True)

    def explain_mode(self):
        self.mode_help.set('Sans IA : texte des PDF, règles et listes. Aucun OCR ni modèle, même au contrôle '
                           'de la copie. Scans et zones graphiques demandent une revue manuelle.'
                           if MODES[self.mode.get()] == 'rules' else
                           'Assisté local : OCR et modèle français sur cet ordinateur. '
                           'Les noms peuvent être proposés à partir des phrases, sans libellé.')

    def import_list(self, source):
        if self.app.busy:
            return
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('Liste CSV', '*.csv *.txt')])
        if path:
            self.app.import_references(path, source)

    def receive_entries(self, source, entries):
        self.entries = tuple(e for e in self.entries if e.source != source) + tuple(entries)
        self.update_counts()

    def update_counts(self):
        for source, count in self.list_counts.items():
            count.set(f'{sum(e.source == source for e in self.entries)} informations en mémoire')

    def apply(self):
        if self.app.busy:
            messagebox.showinfo('Analyse en cours', 'Attendez la fin de l’opération ou annulez-la.',
                                parent=self.window)
            return
        try:
            options = DetectionOptions(tuple(k for k, v in self.variables.items() if v.get()),
                                       tuple(self.terms.get('1.0', 'end').splitlines()),
                                       mode=MODES[self.mode.get()],
                                       profile=next(k for k, v in PROFILES.items() if v == self.profile.get()),
                                       references=self.entries)
            self.app.set_detection_options(options)
        except DocumentError as error:
            messagebox.showinfo('Choix à vérifier', str(error), parent=self.window)
            return
        self.close()

    def close(self):
        self.app.detection_window = None
        self.window.destroy()
        if getattr(self.app, 'batch_controller', False) and self.app.window.winfo_exists():
            self.app.window.grab_set()
