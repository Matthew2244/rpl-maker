"""Entry point for the packaged app: the window, or the command line, or --self-test."""
import os
import sys

# A windowed Windows build may start with no stdout or stderr at all (Wavelength's lesson):
# the self-test and the command line still need somewhere to write.
for _name, _fd in (("stdout", 1), ("stderr", 2)):
    if getattr(sys, _name) is None:
        try:
            setattr(sys, _name, os.fdopen(_fd, "w", buffering=1, encoding="utf-8"))
        except OSError:
            setattr(sys, _name, open(os.devnull, "w"))

from rplmaker import cli, gui, selftest  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--self-test"]:
        sys.exit(selftest.main())
    if args and args[0] in ("list", "build", "checker", "access", "-h", "--help"):
        sys.exit(cli.main(args))
    gui.main()
