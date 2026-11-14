"""Generate a wholly synthetic, two-page document for manual testing."""

import argparse
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def make_demo(path):
    writer = PdfWriter()
    writer.add_metadata({"/Author": "AUTEUR FICTIF A SUPPRIMER", "/Title": "Exemple synthetique"})
    for index in range(2):
        page = writer.add_blank_page(595, 842)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }),
            }),
        })
        lines = [
            "DOCUMENT FICTIF - AUCUNE DONNEE REELLE",
            "Exemple de preparation au partage",
            "Nom : Alex Exemple",
            "Adresse : 12 rue de l'Exemple",
            "Reference privee : DEMO-1234-5678",
            "",
            "Masquez les trois lignes ci-dessus avant de partager.",
            "Les lignes non masquees resteront lisibles dans la copie.",
            "",
            f"Page {index + 1} / 2 - pensez a verifier toutes les pages.",
        ]
        commands = ["0.12 0.25 0.20 rg 45 760 505 4 re f", "BT /F1 14 Tf 45 725 Td"]
        for line in lines:
            commands.append(f"({line}) Tj 0 -34 Td")
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    with Path(path).open("xb") as output:
        writer.write(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    make_demo(parser.parse_args().output)
