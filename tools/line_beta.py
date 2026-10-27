"""Private operator entry point. Binding codes never issued by a public URL."""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from adapters.storage import TenantStore
from adapters.line.shared import BindingRegistry


def main():
    parser = argparse.ArgumentParser(description="封測管理；不開抓取、不收費")
    sub = parser.add_subparsers(dest="command", required=True)
    bind = sub.add_parser("bind", help="在安全終端產生單一租戶綁定碼")
    bind.add_argument("tenant")
    bind.add_argument("--data-dir", help="明確指定服務使用的資料目錄；優先於環境變數")
    serve = sub.add_parser("serve", help="僅本機開發伺服器")
    serve.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if args.command == "bind":
        print(BindingRegistry(TenantStore(args.data_dir)).issue_code(args.tenant))
    else:
        from wsgiref.simple_server import make_server
        from web.line_app import application
        with make_server("127.0.0.1", args.port, application) as server:
            print("本機封測啟動；尚未公開部署")
            server.serve_forever()


if __name__ == "__main__":
    main()
