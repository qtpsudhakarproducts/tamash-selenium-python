from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="tamash-selenium")
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="Check provider connectivity and locator best practices.")
    doctor.add_argument("--dir", default="tests", help="Test directory to scan (default: tests)")

    apply = sub.add_parser("apply-heals", help="Rewrite source locators using selectors confirmed by self-healing runs.")
    apply.add_argument("--dry-run", action="store_true", help="Show what would change without writing files.")
    apply.add_argument("--logs-dir", default=None, help="Merge every heals.jsonl found under this directory (sharded CI).")
    apply.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt.")

    init = sub.add_parser("init-skill", help="Copy the coding-agent skill into .claude/skills and .agents/skills.")
    init.add_argument("--target", choices=["claude", "agents"], default=None)
    init.add_argument("--user", action="store_true", help="Install under your home directory (every project).")
    init.add_argument("--force", action="store_true")
    init.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.command == "doctor":
        from .doctor import run_doctor
        run_doctor(args.dir)
    elif args.command == "apply-heals":
        from .apply_heals import run_apply_heals
        rest = []
        if args.dry_run:
            rest.append("--dry-run")
        if args.yes:
            rest.append("--yes")
        if args.logs_dir:
            rest += ["--logs-dir", args.logs_dir]
        run_apply_heals(rest)
    elif args.command == "init-skill":
        from .skill import run_init_skill
        rest = []
        if args.target:
            rest += ["--target", args.target]
        if args.user:
            rest.append("--user")
        if args.force:
            rest.append("--force")
        if args.dry_run:
            rest.append("--dry-run")
        run_init_skill(rest)
    else:
        parser.print_help()
        sys.exit(1 if args.command else 0)


if __name__ == "__main__":
    main()
