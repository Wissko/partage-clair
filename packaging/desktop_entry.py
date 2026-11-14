"""PyInstaller entry point; no network and no elevated privileges required."""

import sys

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from partage_clair.selfcheck import run
        raise SystemExit(run(sys.argv[2]))
    from partage_clair.gui import main
    main()
