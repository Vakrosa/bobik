"""Обёртка для Cloud Run: держит порт (health) + крутит бота 24/7 с авто-ретраем."""
import os, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from bot import build_application

PORT = int(os.environ.get("PORT", "8080"))

class _H(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def log_message(self, *a): return

def _serve():
    HTTPServer(("0.0.0.0", PORT), _H).serve_forever()

def main():
    # порт биндится сразу и держится, даже если поллинг временно падает
    threading.Thread(target=_serve, daemon=True).start()
    while True:
        try:
            build_application().run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                stop_signals=None,
            )
        except Exception as e:
            print(f"[polling] перезапуск через 8с: {e}", flush=True)
            time.sleep(8)

if __name__ == "__main__":
    main()
