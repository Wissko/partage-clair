import argparse
import json
import sys
from pathlib import Path

from .core import Box, Document


def main(argv=None):
    parser = argparse.ArgumentParser(description="Préparer une copie de partage, hors ligne.")
    parser.add_argument("source", nargs="?", type=Path, help="PDF ou image à traiter")
    parser.add_argument("-o", "--output", type=Path, help="Nouveau PDF ou PNG (jamais écrasé)")
    parser.add_argument("--masks", type=Path, help="JSON : [{page:1, x0:0.1, y0:0.2, x1:0.6, y1:0.3}]")
    parser.add_argument("--dpi", type=int, default=150, help="Résolution du PDF : 72 à 200 (150 par défaut)")
    args = parser.parse_args(argv)
    if args.source is None:
        from .gui import main as gui_main
        gui_main()
        return 0
    if args.output is None:
        parser.error("--output est requis en ligne de commande.")
    try:
        boxes = []
        if args.masks:
            raw = json.loads(args.masks.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("Le fichier de masques doit contenir une liste JSON.")
            boxes = [Box(**item) for item in raw]
        with Document(args.source) as doc:
            result = doc.export(args.output, boxes, args.dpi)
        print(f"Copie créée : {result}")
        print("Vérifiez visuellement chaque page. Les informations visibles non masquées restent lisibles.")
        return 0
    except Exception as error:
        print(f"Export refusé : {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
