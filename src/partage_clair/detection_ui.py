"""Human-selected scope and an in-memory confidential dictionary."""

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .core import DocumentError
from .detection_options import CATEGORIES, DetectionOptions


class DetectionWindow:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Choisir les données à détecter — en local')
        self.window.geometry('850x650')
        self.window.minsize(760, 610)
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Quelles données rechercher ?',
                  font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Tout est sélectionné au départ. Ces choix proposent des zones ; '
                  'seule votre validation les masque.', wraplength=780).pack(anchor='w', pady=(6, 10))
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
        row = ttk.Frame(frame)
        row.pack(fill='x')
        ttk.Button(row, text='Annuler', command=self.close).pack(side='right')
        self.apply_button = ttk.Button(row, text='Appliquer et analyser' if app.doc else 'Appliquer',
                                       command=self.apply, style='Accent.TButton')
        self.apply_button.pack(side='right', padx=8)
        self.window.protocol('WM_DELETE_WINDOW', self.close)

    def select_all(self):
        for variable in self.variables.values():
            variable.set(True)

    def apply(self):
        if self.app.busy:
            messagebox.showinfo('Analyse en cours', 'Attendez la fin de l’opération ou annulez-la.',
                                parent=self.window)
            return
        try:
            options = DetectionOptions(tuple(k for k, v in self.variables.items() if v.get()),
                                       tuple(self.terms.get('1.0', 'end').splitlines()))
        except DocumentError as error:
            messagebox.showinfo('Choix à vérifier', str(error), parent=self.window)
            return
        self.app.set_detection_options(options)
        self.close()

    def close(self):
        self.app.detection_window = None
        self.window.destroy()
