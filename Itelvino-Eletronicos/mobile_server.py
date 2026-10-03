"""Mobile browser interface for the local Itelvino desktop database."""

import base64
import binascii
import ipaddress
import io
import json
import mimetypes
import os
import secrets
import socket
import sqlite3
import tempfile
import threading
import time
import urllib.parse
import uuid
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


MAX_REQUEST_BYTES = 8 * 1024 * 1024
SESSION_SECONDS = 8 * 60 * 60
PAYMENT_METHODS = ("Dinheiro", "PIX", "Cartão de débito", "Cartão de crédito", "Outro")


def _lan_address():
    """Find the IPv4 address Windows routes through, without sending data."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
        if ipaddress.ip_address(address).is_private:
            return address
    except OSError:
        pass
    finally:
        probe.close()
    try:
        addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for result in addresses:
            address = result[4][0]
            parsed = ipaddress.ip_address(address)
            if parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
                return address
    except OSError:
        pass
    return "127.0.0.1"


class _LanHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, owner):
        self.owner = owner
        super().__init__(address, handler)


class MobileServer:
    def __init__(self, database):
        self.db = database
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.login_attempts = {}
        self.login_lock = threading.Lock()
        self.httpd = None
        self.thread = None
        self.url = None
        self.error = None
        self.public_access = False

    def listen(self, host, port, public_access=False):
        self.public_access = public_access
        self.httpd = _LanHTTPServer((host, port), self._make_handler(), self)
        return self.httpd

    def start(self):
        if self.httpd:
            return self.url
        try:
            self.listen("0.0.0.0", 8765)
        except OSError as exc:
            self.error = str(exc)
            return None
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="ItelvinoMobile", daemon=True)
        self.thread.start()
        address = _lan_address()
        self.url = f"http://{address}:{self.httpd.server_port}" if address != "127.0.0.1" else None
        return self.url

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def _session_user(self, token):
        if not token:
            return None
        now = time.monotonic()
        with self.session_lock:
            session = self.sessions.get(token)
            if not session:
                return None
            if session["expires"] <= now:
                self.sessions.pop(token, None)
                return None
            session["expires"] = now + SESSION_SECONDS
            return session["username"]

    def _login_allowed(self, address):
        now = time.monotonic()
        with self.login_lock:
            record = self.login_attempts.get(address)
            if not record:
                return True
            if record["blocked_until"] > now:
                return False
            if now - record["window_start"] > 900:
                self.login_attempts.pop(address, None)
                return True
            return record["failures"] < 10

    def _record_login_failure(self, address):
        now = time.monotonic()
        with self.login_lock:
            record = self.login_attempts.get(address)
            if not record or now - record["window_start"] > 900:
                record = {"window_start": now, "failures": 0, "blocked_until": 0}
                self.login_attempts[address] = record
            record["failures"] += 1
            if record["failures"] >= 10:
                record["blocked_until"] = now + 900

    def _clear_login_failures(self, address):
        with self.login_lock:
            self.login_attempts.pop(address, None)

    def _make_handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ItelvinoMobile"
            sys_version = ""

            def log_message(self, _format, *_args):
                return

            def _is_local(self):
                if owner.public_access:
                    return True
                address = self.client_address[0].split("%", 1)[0]
                try:
                    parsed = ipaddress.ip_address(address)
                    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
                        parsed = parsed.ipv4_mapped
                    return parsed.is_private or parsed.is_loopback
                except ValueError:
                    return False

            def _send(self, status, body=b"", content_type="application/json; charset=utf-8", headers=()):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("X-Robots-Tag", "noindex, nofollow")
                self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _json(self, status, data, headers=()):
                payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._send(status, payload, headers=headers)

            def _body(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise ValueError("Requisição inválida.")
                if length < 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("O arquivo enviado ultrapassa o limite de 8 MB.")
                raw = self.rfile.read(length)
                if not raw:
                    return {}
                try:
                    value = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise ValueError("Os dados enviados não são válidos.")
                if not isinstance(value, dict):
                    raise ValueError("Formato de dados inválido.")
                return value

            def _user(self):
                cookie = self.headers.get("Cookie", "")
                token = ""
                for part in cookie.split(";"):
                    name, separator, value = part.strip().partition("=")
                    if separator and name == "itelvino_session":
                        token = value
                        break
                return owner._session_user(token)

            def _require_user(self):
                username = self._user()
                if not username:
                    self._json(401, {"error": "Entre com seu usuário e senha para continuar."})
                    return None
                return username

            @staticmethod
            def _int(value, label, minimum=0, maximum=2_000_000):
                if isinstance(value, bool):
                    raise ValueError(f"Informe {label} como número inteiro.")
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    raise ValueError(f"Informe {label} como número inteiro.")
                if str(value).strip() not in (str(number), f"+{number}"):
                    raise ValueError(f"Informe {label} como número inteiro.")
                if not minimum <= number <= maximum:
                    raise ValueError(f"{label.capitalize()} deve ficar entre {minimum} e {maximum}.")
                return number

            @staticmethod
            def _number(value, label):
                try:
                    result = float(str(value).replace(",", "."))
                except (TypeError, ValueError):
                    raise ValueError(f"Informe {label} corretamente.")
                if result < 0 or result != result or result == float("inf"):
                    raise ValueError(f"{label.capitalize()} não pode ser negativo.")
                return round(result, 2)

            def _product_data(self, row):
                data = {key: row[key] for key in ("id", "barcode", "description", "quantity", "cost", "price")}
                photo = row["photo_path"]
                data["photo_url"] = f"/api/products/{row['id']}/photo" if photo and Path(photo).is_file() else None
                return data

            def _sale_data(self, row):
                return {key: row[key] for key in ("id", "subtotal", "discount_percent", "discount_value", "total", "payment_method", "installments", "username", "created_at", "item_list")}

            def do_GET(self):
                if not self._is_local():
                    self._json(403, {"error": "Acesso permitido apenas pela rede local."})
                    return
                parsed = urllib.parse.urlsplit(self.path)
                path = urllib.parse.unquote(parsed.path)
                query = urllib.parse.parse_qs(parsed.query)
                if path == "/" or path == "/mobile.html":
                    try:
                        page = Path(__file__).with_name("mobile.html").read_bytes()
                    except OSError:
                        self._send(404, "Interface móvel não encontrada.", "text/plain; charset=utf-8")
                        return
                    self._send(200, page, "text/html; charset=utf-8")
                    return
                if path == "/logo.jpg":
                    try:
                        logo = Path(__file__).with_name("logo.jpg").read_bytes()
                    except OSError:
                        self._send(404, "", "text/plain")
                        return
                    self._send(200, logo, "image/jpeg")
                    return
                if path == "/api/status":
                    self._json(200, {"setup_needed": not owner.db.has_user()})
                    return
                username = self._require_user()
                if not username:
                    return
                if path == "/api/me":
                    self._json(200, {"username": username})
                elif path == "/api/products":
                    search = query.get("q", [""])[0].strip()
                    self._json(200, {"products": [self._product_data(row) for row in owner.db.products(search)]})
                elif path.startswith("/api/products/") and path.endswith("/photo"):
                    pieces = path.strip("/").split("/")
                    try:
                        product_id = int(pieces[2])
                        product = owner.db.product(product_id)
                        photo_path = Path(product["photo_path"]) if product and product["photo_path"] else None
                        if not photo_path or not photo_path.is_file():
                            raise FileNotFoundError
                        image = photo_path.read_bytes()
                        if len(image) > 8 * 1024 * 1024:
                            raise OSError("Imagem muito grande")
                        content_type = mimetypes.guess_type(str(photo_path))[0] or "application/octet-stream"
                        if not content_type.startswith("image/"):
                            raise OSError("Arquivo não é imagem")
                        self._send(200, image, content_type)
                    except (ValueError, IndexError, OSError, TypeError):
                        self._send(404, "", "text/plain")
                elif path == "/api/reports":
                    day_text = query.get("day", [datetime.now().strftime("%Y-%m-%d")])[0]
                    month_text = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
                    sale_number = query.get("sale", [""])[0].strip().lstrip("#")
                    item_query = query.get("item", [""])[0].strip()
                    try:
                        datetime.strptime(day_text, "%Y-%m-%d")
                        datetime.strptime(month_text, "%Y-%m")
                        if sale_number and not sale_number.isdigit():
                            raise ValueError("O número da venda deve conter apenas números.")
                        sales, payments, daily_summary, daily_items = owner.db.daily_sales(day_text, sale_number, item_query)
                        monthly_summary, monthly_items, monthly_methods, monthly_sales = owner.db.monthly_sales(month_text, sale_number, item_query)
                    except ValueError as exc:
                        self._json(400, {"error": str(exc)})
                        return
                    self._json(200, {
                        "day": day_text,
                        "month": month_text,
                        "daily": {"summary": dict(daily_summary), "items": dict(daily_items), "payments": [dict(row) for row in payments], "sales": [self._sale_data(row) for row in sales]},
                        "monthly": {"summary": dict(monthly_summary), "items": dict(monthly_items), "methods": [dict(row) for row in monthly_methods], "sales": [self._sale_data(row) for row in monthly_sales]},
                    })
                elif path == "/api/movements":
                    month_text = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
                    kind = query.get("kind", ["Todos"])[0]
                    sale_number = query.get("sale", [""])[0].strip().lstrip("#")
                    item_query = query.get("item", [""])[0].strip()
                    if kind not in ("Todos", "Entradas", "Saídas") or (sale_number and not sale_number.isdigit()):
                        self._json(400, {"error": "Revise os filtros da movimentação."})
                        return
                    try:
                        datetime.strptime(month_text, "%Y-%m")
                        totals, rows = owner.db.monthly_movements(month_text, kind, sale_number, item_query)
                    except ValueError as exc:
                        self._json(400, {"error": str(exc)})
                        return
                    self._json(200, {"totals": totals, "rows": [dict(row) for row in rows]})
                elif path == "/api/backup":
                    self._send_backup()
                else:
                    self._json(404, {"error": "Endereço não encontrado."})

            def _send_backup(self):
                backup_root = owner.db.path.parent
                handle, temp_path = tempfile.mkstemp(prefix="itelvino-backup-", suffix=".db", dir=backup_root)
                os.close(handle)
                try:
                    with sqlite3.connect(owner.db.path) as source, sqlite3.connect(temp_path) as target:
                        source.backup(target)
                    output = io.BytesIO()
                    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                        archive.write(temp_path, "itelvino.db")
                        photos = backup_root / "mobile_photos"
                        if photos.is_dir():
                            for photo in photos.iterdir():
                                if photo.is_file():
                                    archive.write(photo, f"mobile_photos/{photo.name}")
                    data = output.getvalue()
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    self._send(200, data, "application/zip", (("Content-Disposition", f'attachment; filename="itelvino-backup-{stamp}.zip"'),))
                finally:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass

            def do_POST(self):
                if not self._is_local():
                    self._json(403, {"error": "Acesso permitido apenas pela rede local."})
                    return
                path = urllib.parse.urlsplit(self.path).path
                try:
                    data = self._body()
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                if path == "/api/login":
                    username = str(data.get("username", "")).strip()
                    password = str(data.get("password", ""))
                    address = self.client_address[0]
                    if not owner._login_allowed(address):
                        self._json(429, {"error": "Muitas tentativas. Aguarde 15 minutos e tente novamente."})
                        return
                    if not username or not password or not owner.db.authenticate(username, password):
                        owner._record_login_failure(address)
                        self._json(401, {"error": "Usuário ou senha incorretos."})
                        return
                    owner._clear_login_failures(address)
                    username = owner.db.canonical_username(username)
                    self._start_session(username)
                    return
                if path == "/api/setup":
                    if owner.db.has_user():
                        self._json(409, {"error": "A configuração inicial já foi concluída."})
                        return
                    setup_key = os.environ.get("ITELVINO_SETUP_KEY", "")
                    supplied_key = str(data.get("setup_key", ""))
                    if not setup_key or not secrets.compare_digest(setup_key, supplied_key):
                        self._json(401, {"error": "A chave de configuração está incorreta."})
                        return
                    username = str(data.get("username", "")).strip()
                    password = str(data.get("password", ""))
                    if not username or len(username) > 80:
                        self._json(400, {"error": "Informe um nome de usuário válido."})
                        return
                    if len(password) < 6:
                        self._json(400, {"error": "Use uma senha com pelo menos 6 caracteres."})
                        return
                    try:
                        owner.db.setup_user(username, password)
                    except sqlite3.IntegrityError:
                        self._json(409, {"error": "A configuração inicial já foi concluída."})
                        return
                    self._start_session(owner.db.canonical_username(username))
                    return
                username = self._require_user()
                if not username:
                    return
                try:
                    if path == "/api/logout":
                        cookie = self.headers.get("Cookie", "")
                        token = next((part.strip().split("=", 1)[1] for part in cookie.split(";") if part.strip().startswith("itelvino_session=")), "")
                        with owner.session_lock:
                            owner.sessions.pop(token, None)
                        self._json(200, {"ok": True}, (("Set-Cookie", "itelvino_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"),))
                    elif path == "/api/products":
                        self._save_product(data, username)
                    elif path == "/api/stock":
                        self._save_movement(data, username)
                    elif path == "/api/sales":
                        self._save_sale(data, username)
                    elif path == "/api/users":
                        self._add_user(data)
                    elif path == "/api/password":
                        self._change_password(data, username)
                    else:
                        self._json(404, {"error": "Endereço não encontrado."})
                except sqlite3.IntegrityError as exc:
                    message = "Esse código de barras já está cadastrado." if "unique" in str(exc).lower() else "Não foi possível gravar os dados."
                    self._json(409, {"error": message})
                except (ValueError, OSError, binascii.Error) as exc:
                    self._json(400, {"error": str(exc)})
                except Exception:
                    self._json(500, {"error": "Ocorreu um erro ao processar a solicitação."})

            def _start_session(self, username):
                token = secrets.token_urlsafe(32)
                with owner.session_lock:
                    owner.sessions[token] = {"username": username, "expires": time.monotonic() + SESSION_SECONDS}
                secure = "; Secure" if owner.public_access else ""
                cookie = f"itelvino_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}{secure}"
                self._json(200, {"username": username}, (("Set-Cookie", cookie),))

            def _add_user(self, data):
                username = str(data.get("username", "")).strip()
                password = str(data.get("password", ""))
                if not username or len(username) > 80:
                    raise ValueError("Informe um nome de usuário válido.")
                if len(password) < 6:
                    raise ValueError("Use uma senha com pelo menos 6 caracteres.")
                owner.db.add_user(username, password)
                self._json(200, {"ok": True})

            def _change_password(self, data, username):
                current = str(data.get("current_password", ""))
                new_password = str(data.get("new_password", ""))
                if len(new_password) < 6:
                    raise ValueError("Use uma nova senha com pelo menos 6 caracteres.")
                owner.db.change_password(username, current, new_password)
                self._json(200, {"ok": True})

            def _save_product(self, data, username):
                barcode = str(data.get("barcode", "")).strip()
                description = str(data.get("description", "")).strip()
                if not barcode or not description:
                    raise ValueError("Informe o código de barras e a descrição.")
                if len(barcode) > 80 or len(description) > 240:
                    raise ValueError("Código ou descrição muito longo.")
                cost = self._number(data.get("cost", 0), "preço de custo")
                price = self._number(data.get("price", 0), "preço de venda")
                product_id = self._int(data.get("id", 0), "produto", 0)
                initial_qty = self._int(data.get("initial_qty", 0), "estoque inicial", 0)
                existing = owner.db.product(product_id) if product_id else None
                if product_id and not existing:
                    raise ValueError("Produto não encontrado.")
                photo_path = existing["photo_path"] if existing else None
                if data.get("remove_photo"):
                    photo_path = None
                photo_data = data.get("photo_data")
                if photo_data:
                    photo_path = self._store_photo(photo_data)
                saved_id = owner.db.save_product(product_id or None, barcode, description, cost, price, initial_qty, photo_path, username)
                self._json(200, {"ok": True, "id": saved_id})

            def _store_photo(self, encoded):
                header, separator, payload = str(encoded).partition(",")
                if not separator or not header.startswith("data:image/") or ";base64" not in header:
                    raise ValueError("Envie uma foto JPEG ou PNG.")
                mime = header[5:].split(";", 1)[0].lower()
                extension = {"image/jpeg": ".jpg", "image/png": ".png"}.get(mime)
                if not extension:
                    raise ValueError("A foto deve ser JPEG ou PNG.")
                raw = base64.b64decode(payload, validate=True)
                if not raw or len(raw) > 5 * 1024 * 1024:
                    raise ValueError("A foto deve ter no máximo 5 MB.")
                photo_dir = owner.db.path.parent / "mobile_photos"
                photo_dir.mkdir(parents=True, exist_ok=True)
                target = photo_dir / f"{uuid.uuid4().hex}{extension}"
                target.write_bytes(raw)
                return str(target)

            def _save_movement(self, data, username):
                product_id = self._int(data.get("product_id"), "produto", 1)
                kind = str(data.get("kind", ""))
                if kind not in ("Entrada", "Saída"):
                    raise ValueError("Escolha entrada ou saída.")
                if kind == "Saída":
                    kind = "Saída manual"
                quantity = self._int(data.get("quantity"), "quantidade", 1)
                product = owner.db.product(product_id)
                if not product:
                    raise ValueError("Produto não encontrado.")
                cost_text = data.get("unit_cost")
                cost = self._number(cost_text, "custo unitário") if str(cost_text or "").strip() else float(product["cost"])
                note = str(data.get("note", "")).strip()[:240]
                owner.db.stock_movement(product_id, kind, quantity, cost, note, username)
                self._json(200, {"ok": True})

            def _save_sale(self, data, username):
                cart_data = data.get("items")
                if not isinstance(cart_data, list) or not cart_data:
                    raise ValueError("Adicione pelo menos um produto à venda.")
                cart = []
                for line in cart_data:
                    if not isinstance(line, dict):
                        raise ValueError("Item da venda inválido.")
                    product_id = self._int(line.get("product_id"), "produto", 1)
                    quantity = self._int(line.get("quantity"), "quantidade", 1)
                    product = owner.db.product(product_id)
                    if not product:
                        raise ValueError("Um dos produtos não foi encontrado.")
                    cart.append({"id": product["id"], "barcode": product["barcode"], "description": product["description"], "price": float(product["price"]), "qty": quantity})
                discount = self._number(data.get("discount_percent", 0), "desconto")
                if discount > 100:
                    raise ValueError("O desconto deve ficar entre 0% e 100%.")
                payment = str(data.get("payment_method", ""))
                if payment not in PAYMENT_METHODS:
                    raise ValueError("Escolha uma forma de pagamento válida.")
                installments = self._int(data.get("installments", 1), "parcelas", 1, 48)
                result = owner.db.complete_sale(cart, discount, payment, installments, username)
                self._json(200, {"ok": True, "sale_id": result[0], "subtotal": result[1], "discount": result[2], "total": result[3]})

        return Handler
