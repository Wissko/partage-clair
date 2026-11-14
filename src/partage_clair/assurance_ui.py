"""Human review and transparent preparation score; never applies a redaction."""

import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .assurance import CRITERIA, anonymous_summary


class AssuranceWindow:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Préparation à l’anonymisation — score et revue locale')
        self.window.geometry('940x650')
        self.window.minsize(780, 580)
        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill='both', expand=True)
        self.title = tk.StringVar()
        ttk.Label(frame, textvariable=self.title, font=('Segoe UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Score de préparation interne, pas une probabilité ni une certification CNIL. '
                  'Même au maximum de 95/100, l’anonymat n’est pas garanti.', wraplength=900).pack(anchor='w', pady=6)
        notebook = ttk.Notebook(frame)
        notebook.pack(fill='both', expand=True)
        score_tab, review_tab, copy_tab = (ttk.Frame(notebook, padding=12) for _ in range(3))
        for tab, text in ((score_tab, 'Score expliqué'), (review_tab, 'Revue des 3 risques'),
                          (copy_tab, 'Contrôle de la copie')):
            notebook.add(tab, text=text)
        self.details = tk.Text(score_tab, wrap='word', bg='white', fg='#20342c',
                               font=('Segoe UI', 10), relief='flat', state='disabled')
        scroll = ttk.Scrollbar(score_tab, command=self.details.yview)
        self.details.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.details.pack(fill='both', expand=True)
        ttk.Label(review_tab, text='Définissez ce qui est utile à conserver et à qui la copie est destinée. '
                  'Masquez les détails inutiles ou trop précis depuis les suggestions ou la page.',
                  wraplength=850).pack(anchor='w')
        self.purpose = tk.StringVar(value=app.purpose)
        self.audience = tk.StringVar(value=app.audience)
        ttk.Label(review_tab, text='Utilité / informations nécessaires à conserver (mémoire seulement) :').pack(anchor='w', pady=(8, 2))
        ttk.Entry(review_tab, textvariable=self.purpose).pack(fill='x')
        ttk.Label(review_tab, text='Destinataires et possibilités de recoupement :').pack(anchor='w', pady=(6, 2))
        ttk.Combobox(review_tab, textvariable=self.audience, state='readonly',
                     values=('Publication publique', 'Destinataires identifiés', 'Usage interne restreint')).pack(fill='x')
        self.checks = {}
        for key, (name, explanation) in CRITERIA.items():
            ttk.Label(review_tab, text=f'{name} — {explanation}', wraplength=850).pack(anchor='w', pady=(9, 0))
            variable = tk.BooleanVar(value=False)
            self.checks[key] = variable
            ttk.Checkbutton(review_tab, text=f'J’ai examiné le risque d’{name.lower()}'
                            if key != 'correlation' else 'J’ai examiné le risque de corrélation',
                            variable=variable, command=self.context_changed).pack(anchor='w')
        self.confirm_review = ttk.Button(review_tab, text='Valider ma revue pour cet état du document',
                                         command=self.validate_review)
        self.confirm_review.pack(anchor='w', pady=10)
        self.review_status = tk.StringVar()
        ttk.Label(review_tab, textvariable=self.review_status, wraplength=850).pack(anchor='w')
        self.audit_status = tk.StringVar()
        ttk.Label(copy_tab, text='1. Exportez une nouvelle copie, puis contrôlez-la ici.\n'
                  '2. Ouvrez-la et relisez toutes les pages, y compris photos, QR, codes-barres et contexte.\n'
                  '3. Confirmez votre relecture. Un contrôle OCR peut manquer du texte.',
                  wraplength=850).pack(anchor='w', pady=(0, 12))
        buttons = ttk.Frame(copy_tab)
        buttons.pack(fill='x')
        self.audit_button = ttk.Button(buttons, text='Contrôler la copie en local', command=app.audit_copy)
        self.audit_button.pack(side='left')
        self.open_button = ttk.Button(buttons, text='Ouvrir la copie', command=app.open_output)
        self.open_button.pack(side='left', padx=8)
        ttk.Label(copy_tab, textvariable=self.audit_status, wraplength=850).pack(anchor='w', pady=12)
        self.copy_read = tk.BooleanVar(value=False)
        ttk.Checkbutton(copy_tab, text='J’ai ouvert et relu toutes les pages de cette copie.',
                         variable=self.copy_read).pack(anchor='w')
        self.confirm_copy = ttk.Button(copy_tab, text='Enregistrer ma relecture pour cette copie',
                                       command=self.validate_copy)
        self.confirm_copy.pack(anchor='w', pady=8)
        ttk.Label(copy_tab, text='Les validations de revue deviennent caduques si vous changez les masques, '
                  'ajoutez une recherche ou relancez l’analyse. Toute nouvelle copie doit être contrôlée '
                  'et relue. Le bilan JSON ne contient ni texte OCR, ni noms, ni chemins.', wraplength=850).pack(anchor='w', pady=10)
        ttk.Button(frame, text='Enregistrer un bilan local sans valeurs reconnues…', command=self.save_summary).pack(anchor='w', pady=(10, 0))
        self.purpose.trace_add('write', lambda *_: self.context_changed())
        self.audience.trace_add('write', lambda *_: self.context_changed())
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()

    def context_changed(self):
        self.app.purpose = self.purpose.get()[:500]
        self.app.audience = self.audience.get()
        self.app.criteria_snapshot, self.app.copy_snapshot = None, None
        self.app.refresh_score()

    def validate_review(self):
        if self.app.busy or self.app.report is None:
            return
        if not self.app.purpose.strip() or not self.app.audience or not all(v.get() for v in self.checks.values()):
            messagebox.showinfo('Revue à compléter', 'Renseignez l’utilité, les destinataires et examinez les trois risques.', parent=self.window)
            return
        self.app.criteria_snapshot = self.app.review_signature()
        self.app.refresh_score()

    def validate_copy(self):
        audit = self.app.current_audit()
        if (not self.app.busy and audit and audit.passed and self.copy_read.get()
                and self.app.criteria_snapshot == self.app.review_signature()):
            self.app.copy_snapshot = self.app.review_signature()
            self.app.refresh_score()
        else:
            messagebox.showinfo('Relecture à compléter', 'Validez la revue des risques, contrôlez la copie actuelle '
                                'et confirmez avoir relu toutes ses pages.', parent=self.window)

    def refresh(self):
        app = self.app
        score = app.get_preparation_score()
        self.title.set('Score de préparation : ' + (f'{score.value}/100' if score.value is not None else 'analyse requise'))
        lines = [f'{name} : {points}/{maximum}' for name, points, maximum in score.components]
        lines += ['', f'Groupes encore exposés : {score.direct_remaining} directs ; {score.indirect_remaining} indirects.',
                  '', 'Points à traiter :', *('• ' + b for b in score.blockers), '',
                  'Signaux à examiner (pas une mesure de risque) :']
        for key, (name, _) in CRITERIA.items():
            lines.append(f'• {name} : ' + ('indices encore exposés' if key in score.flags else
                          'aucun signal restant parmi les motifs reconnus ; examen humain nécessaire'))
        lines += ['', 'Pondérations propres au projet : maximum 95. Plafond 49 si analyse incomplète ou '
                  'identifiants directs exposés ; 69 si indices indirects, revue ou copie à vérifier ; '
                  '39 en cas d’anomalie technique. Les points ne mesurent ni k-anonymat, ni l-diversité, '
                  'ni probabilité de réidentification. Voir docs/ANONYMISATION.md pour la méthode.']
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', '\n'.join(lines))
        self.details.configure(state='disabled')
        valid = app.criteria_snapshot == app.review_signature()
        self.review_status.set('Revue déclarée pour l’état actuel ; risque externe non mesuré.' if valid
                               else 'Revue à compléter ou devenue caduque.')
        ready = bool(app.last_output) and not app.dirty() and not app.busy
        for button in (self.audit_button, self.open_button):
            button.configure(state='normal' if ready else 'disabled')
        self.confirm_review.configure(state='normal' if app.report and not app.busy else 'disabled')
        self.confirm_copy.configure(state='normal' if ready else 'disabled')
        audit = app.current_audit()
        if audit:
            self.audit_status.set(f'Contrôle technique : {"passé" if audit.passed else "incomplet ou anomalie"}. '
                f'{audit.approved_residuals} groupe(s) validé(s) encore reconnus ; '
                f'{audit.residual_groups} proposition(s) restante(s) dans la copie.\n'
                f'SHA-256 de la copie : {audit.sha256}\n' + ' '.join(audit.warnings) +
                ('\nRelecture déclarée pour cette copie.' if app.copy_snapshot == app.review_signature() else ''))
        else:
            self.audit_status.set('Copie actuelle non contrôlée. Aucune preuve technique attribuée au score.')

    def save_summary(self):
        if self.app.busy:
            return
        path = filedialog.asksaveasfilename(parent=self.window, initialfile='bilan-preparation.json',
                                           defaultextension='.json', filetypes=[('Bilan JSON', '*.json')])
        if path:
            try:
                payload = anonymous_summary(self.app.get_preparation_score(), self.app.current_audit())
                with open(path, 'x', encoding='utf-8') as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
            except OSError:
                messagebox.showerror('Bilan non enregistré', 'Choisissez un nouveau fichier accessible. '
                                     'Aucun fichier existant ne sera remplacé.', parent=self.window)

    def close(self):
        self.app.assurance_window = None
        self.window.destroy()
