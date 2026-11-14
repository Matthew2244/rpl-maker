import sys

args = sys.argv[1:]
if args[:1] == ["--self-test"]:
    from .selftest import main as st
    sys.exit(st())
if args:
    from .cli import main
    sys.exit(main())
from .gui import main
main()
