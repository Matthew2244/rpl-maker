"""The command-line way in: list what can be made, make some, read the report.

    python -m rplmaker list [--all] [--folder DIR ...]
    python -m rplmaker build NAME [NAME ...] [--out DIR] [--by NAME] [--min 5] [--once] [--folder DIR ...]
    python -m rplmaker organize FOLDER [--out DIR] [--per-category] [--no-prefix] [--layout maker]
    python -m rplmaker checker                # make or remake the checking copy of REAPER

NAME matches a plug-in's name, any part, any case ("ozone 12 eq" finds Ozone 12 Equalizer).
Writes one line per event and the report path at the end; nothing rewrites a line in place.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import APP_NAME, formats, inreaper, inventory, organize, pipeline, portable, settings


def _scan(folders):
    def progress(stage, a, b):
        pass
    return inventory.scan(folders, progress=progress)


def main(argv=None) -> int:
    cfg = settings.load()
    ap = argparse.ArgumentParser(prog="rplmaker", description=f"{APP_NAME}: make REAPER preset libraries "
                                 "from the factory presets your plug-ins installed.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list", help="plug-ins with preset files this can read")
    a.add_argument("--all", action="store_true", help="also list plug-ins with no preset files found")
    a.add_argument("--folder", action="append", default=[], help="another folder to look in for presets")
    b = sub.add_parser("build", help="make and check libraries")
    b.add_argument("names", nargs="+", help="plug-in names, or parts of them")
    b.add_argument("--out", default=cfg["out_dir"], help=f"where libraries go (now: {cfg['out_dir']})")
    b.add_argument("--by", default=cfg["author"], help=f"your name in the file names (now: {cfg['author'] or 'none'})")
    b.add_argument("--min", type=int, default=cfg["min_keep"], help=f"smallest library worth keeping (now: {cfg['min_keep']})")
    b.add_argument("--once", action="store_true", help="check each preset once, not twice")
    b.add_argument("--split", type=int, default=cfg["split_over"] if cfg["split_big"] else 0,
                   help="one library per folder when a plug-in has more presets than this; 0 never "
                        f"(now: {cfg['split_over'] if cfg['split_big'] else 0})")
    b.add_argument("--folder", action="append", default=[], help="another folder to look in for presets")
    o = sub.add_parser("organize", help="copy a folder of existing libraries into a new folder, organized: "
                       "names start with their maker's category where it's known, a folder per plug-in")
    o.add_argument("folder", help="the folder of .RPL files to organize; it isn't changed")
    o.add_argument("--out", help="where the organized copy goes (default: beside it, named '... (organized)')")
    o.add_argument("--folder-for-presets", dest="extra", action="append", default=[],
                   help="another folder to look in for the makers' preset files, for their categories")
    for q in (b, o):
        q.add_argument("--no-prefix", action="store_true",
                       help=f"don't start preset names with their category (now: {'on' if cfg['prefix_category'] else 'off'})")
        q.add_argument("--per-category", action="store_true", default=bool(cfg["per_category"]),
                       help=f"one library per category (now: {'on' if cfg['per_category'] else 'off'})")
        q.add_argument("--layout", choices=sorted(organize.LAYOUTS), default=cfg["layout"],
                       help=f"plugin: a folder per maker, then per plug-in; maker: per maker only (now: {cfg['layout']})")
    sub.add_parser("checker", help="make or remake the checking copy of REAPER")
    sub.add_parser("access", help="Mac: let macOS ask, now, whether the checking copy may open your folders and "
                   "drives. Windows: check every preset folder can be read and libraries can be saved")
    args = ap.parse_args(argv)

    if args.cmd == "checker":
        portable.make(progress=print)
        return 0
    if args.cmd == "access":
        if portable.WIN:   # the Windows counterpart: read every folder, save a test file
            from . import access
            plugs = _scan(cfg["extra_folders"])
            found = {os.path.dirname(f.path) for p in plugs for fs in p.presets.values() for f in fs}
            out = os.path.expanduser(cfg["out_dir"])
            rep = access.check(list(inventory.SEARCH_ROOTS) + sorted(found), out, required=cfg["extra_folders"])
            print(rep.details(out))
            return 0 if not rep.problems else 3   # 3: problems found (1 would read as a crash)
        if portable.status() != "ready":
            portable.make(progress=print)
        print("macOS may ask, once per place, whether REAPER for checking presets can open files there. Choose Allow.")
        for d, ok in pipeline.allow_folders(events=lambda k, d: print("Opening", d, flush=True)):
            print(("  allowed: " if ok else "  not allowed or empty: ") + d)
        return 0
    if args.cmd == "organize":
        src = os.path.expanduser(args.folder)
        if not os.path.isdir(src):
            print(f"There's no folder at {src}.")
            return 2
        dst = os.path.expanduser(args.out) if args.out else organize.organized_name(src)
        print("Looking for the makers' preset files, for their categories.", flush=True)
        plugs = _scan(cfg["extra_folders"] + args.extra)
        try:
            stats = organize.organize_folder(src, dst, plugs, prefix=cfg["prefix_category"] and not args.no_prefix,
                                             per_category=args.per_category, layout=args.layout,
                                             min_keep=int(cfg["min_keep"]),
                                             log=lambda s: print("  " + s, flush=True))
        except (OSError, ValueError) as e:
            print(f"Couldn't organize it: {e}")
            return 2
        text = organize.report_text(stats, src, dst)
        path = organize.save_report(text)
        print(text)
        print("Report:", path)
        return 0
    plugs = _scan(cfg["extra_folders"] + args.folder)
    if args.cmd == "list":
        shown = [p for p in plugs if p.count or args.all]
        for p in shown:
            fmt, f = p.best()
            done = inreaper.done_of(p)
            print((inreaper.status_words(done) + ": " if done and f else "")
                  + (f"{p.name} ({p.vendor}): {len(f)} {formats.FORMAT_WORDS.get(fmt, 'no preset files')}" if f else
                     f"{p.name} ({p.vendor}): no preset files found"))
        print(f"{sum(1 for p in plugs if p.count)} of {len(plugs)} plug-ins have preset files this can read.")
        return 0
    chosen = []
    for want in args.names:
        w = inventory.norm(want)
        hit = [p for p in plugs if inventory.norm(p.name) == w] or [p for p in plugs if w in inventory.norm(p.name)]
        if not hit:
            print(f"No installed plug-in matches {want!r}.")
            return 2
        chosen += [p for p in hit if p not in chosen]
    for p in [p for p in chosen if not p.count]:
        print(f"No preset files this can read were found for {p.name}, so it's skipped.")
    chosen = [p for p in chosen if p.count]
    if not chosen:
        return 2
    if portable.status() == "missing":
        print("REAPER isn't installed on this computer, so there's nothing to check presets with.")
        return 2
    if portable.status() != "ready":
        print("Making the checking copy of REAPER first.")
        portable.make(progress=print)

    def events(kind, *a):
        if kind == "plugin":
            p, i, n = a
            print(f"{i} of {n}: {p.name}, {p.count} {formats.FORMAT_WORDS.get(p.best()[0], '')}", flush=True)
        elif kind == "preset":
            label, k, n = a
            if k == n or k % 100 == 0:
                print(f"  {label}: {k} of {n}", flush=True)
        elif kind == "waiting":
            print("  " + a[1], flush=True)
        elif kind == "result":
            print("  " + a[0].sentence(), flush=True)
    bld = pipeline.Builder(os.path.expanduser(args.out), author=args.by, min_keep=args.min,
                           check_twice=not args.once, split_over=args.split, events=events,
                           prefix=cfg["prefix_category"] and not args.no_prefix, per_category=args.per_category,
                           layout=args.layout)
    try:
        results = bld.build(chosen)
    except portable.CheckerError as e:
        print(e)
        return 2
    except KeyboardInterrupt:
        bld.abort()
        print("Stopped.")
        return 130
    path = pipeline.write_report(results, os.path.expanduser(args.out))
    print("Report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
