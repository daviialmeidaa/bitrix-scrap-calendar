# main.py
import sys
import argparse

def run_scrape():
    from bot import main as bot_main
    return bot_main()

def run_sync():
    from sync_gcal import main as sync_main
    return sync_main()

def parse_args():
    p = argparse.ArgumentParser(description="Bitrix → Google Calendar")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--scrape", action="store_true", help="Coleta notificações no Bitrix e atualiza out/events.json")
    g.add_argument("--sync",   action="store_true", help="Sincroniza out/events.json com o Google Calendar")
    g.add_argument("--all",    action="store_true", help="Executa scrape e depois sync")
    return p.parse_args()

def main():
    args = parse_args()
    try:
        if args.scrape:
            run_scrape()
        elif args.sync:
            run_sync()
        elif args.all:
            run_scrape()
            run_sync()
        return 0
    except SystemExit as e:
        # se bot/sync usarem sys.exit, normaliza para 0
        return int(getattr(e, "code", 0) or 0)
    except Exception as e:
        print(f"[MAIN][ERR] {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
