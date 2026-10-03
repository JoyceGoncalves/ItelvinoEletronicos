import hashlib
import os
import secrets
import shutil
import sqlite3
import subprocess
import tkinter as tk
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from mobile_server import MobileServer
from database import Database, data_directory


APP_NAME = "Itelvino Eletrônicos"
THUMBNAIL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$source = $env:ITELVINO_IMAGE_SOURCE
$target = $env:ITELVINO_IMAGE_TARGET
$maxSide = [int]$env:ITELVINO_IMAGE_SIZE
$image = [System.Drawing.Image]::FromFile($source)
$scale = [Math]::Min($maxSide / $image.Width, $maxSide / $image.Height)
$width = [Math]::Max(1, [int][Math]::Round($image.Width * $scale))
$height = [Math]::Max(1, [int][Math]::Round($image.Height * $scale))
$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$graphics.DrawImage($image, 0, 0, $width, $height)
$bitmap.Save($target, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
$image.Dispose()
"""


def money(value):
    return "R$ " + f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_money(value):
    text = value.strip().replace("R$", "").replace(" ", "")
    if not text:
        raise ValueError("Informe um valor.")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    result = float(text)
    if result < 0:
        raise ValueError("O valor não pode ser negativo.")
    return result


class ItelvinoApp:
    BG = "#f3f5f9"
    NAVY = "#172554"
    BLUE = "#2457c5"
    TEXT = "#1f2937"
    MUTED = "#687386"

    def __init__(self, root):
        self.root = root
        self.db = Database()
        self.mobile_server = MobileServer(self.db)
        self.mobile_url = self.mobile_server.start()
        self.logo_path = Path(__file__).with_name("logo.jpg")
        self.root.title(APP_NAME)
        self.root.geometry("1200x780")
        self.root.minsize(980, 660)
        self.root.configure(bg=self.BG)
        self.configure_style()
        self.show_auth()

    def configure_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.BG)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self.NAVY, foreground="white", font=("Segoe UI", 17, "bold"))
        style.configure("SubTitle.TLabel", background=self.NAVY, foreground="#cbd5e1", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8), borderwidth=0)
        style.configure("Accent.TButton", background=self.BLUE, foreground="white", font=("Segoe UI", 10, "bold"), padding=(14, 9))
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("pressed", "#193f9b")], foreground=[("active", "white")])
        style.configure("Header.TButton", background=self.NAVY, foreground="white", font=("Segoe UI", 9, "bold"), padding=(10, 7))
        style.map("Header.TButton", background=[("active", "#29417d")], foreground=[("active", "white")])
        style.configure("TEntry", fieldbackground="white", bordercolor="#cbd5e1", padding=(7, 6))
        style.configure("TCombobox", fieldbackground="white", bordercolor="#cbd5e1", padding=(6, 5), arrowcolor=self.BLUE)
        style.map("TCombobox", fieldbackground=[("readonly", "white")], foreground=[("readonly", self.TEXT)])
        style.configure("Treeview", rowheight=32, font=("Segoe UI", 9), background="white", fieldbackground="white", borderwidth=0)
        style.map("Treeview", background=[("selected", self.BLUE)], foreground=[("selected", "white")])
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#e8edf5", foreground=self.NAVY, padding=(8, 8))
        style.configure("TNotebook", background=self.BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=(16, 10), background="#e8edf5", foreground=self.MUTED)
        style.map("TNotebook.Tab", background=[("selected", "white"), ("active", "#dbeafe")], foreground=[("selected", self.BLUE)])
        style.configure("TLabelframe", background=self.BG, bordercolor="#dbe3ef", relief="solid")
        style.configure("TLabelframe.Label", background=self.BG, foreground=self.NAVY, font=("Segoe UI", 10, "bold"))
        style.configure("Filter.TLabelframe", background="white", bordercolor="#dbe3ef", relief="solid")
        style.configure("Filter.TLabelframe.Label", background="white", foreground=self.NAVY, font=("Segoe UI", 9, "bold"))

    def load_thumbnail(self, image_path, max_side=220):
        if not image_path or not Path(image_path).is_file():
            return None
        source = Path(image_path).resolve()
        stat = source.stat()
        cache_key = f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{max_side}"
        cache_name = hashlib.sha256(cache_key.encode("utf-8")).hexdigest() + ".png"
        cache_dir = data_directory() / "thumbnails"
        cache_dir.mkdir(parents=True, exist_ok=True)
        thumbnail = cache_dir / cache_name
        if not thumbnail.exists():
            if os.name != "nt":
                return tk.PhotoImage(file=str(source))
            environment = os.environ.copy()
            environment["ITELVINO_IMAGE_SOURCE"] = str(source)
            environment["ITELVINO_IMAGE_TARGET"] = str(thumbnail)
            environment["ITELVINO_IMAGE_SIZE"] = str(max_side)
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", THUMBNAIL_SCRIPT],
                capture_output=True,
                text=True,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0 or not thumbnail.exists():
                details = completed.stderr.strip() or "Não foi possível criar a miniatura da foto."
                raise RuntimeError(details)
        return tk.PhotoImage(file=str(thumbnail))

    def show_photo(self, widget, image_path, empty_text="Sem foto", max_side=220):
        try:
            photo = self.load_thumbnail(image_path, max_side) if image_path else None
        except Exception:
            photo = None
        if photo:
            widget.configure(image=photo, text="", anchor="center", padx=6, pady=6)
            widget.image = photo
        else:
            widget.configure(image="", text=empty_text, anchor="center", padx=6, pady=6)
            widget.image = None

    def show_auth(self):
        self.clear_root()
        wrap = tk.Frame(self.root, bg=self.BG)
        wrap.place(relx=.5, rely=.5, anchor="center")
        card = tk.Frame(wrap, bg="white", padx=28, pady=26, highlightbackground="#dbe2ed", highlightthickness=1)
        card.pack()
        brand = tk.Frame(card, bg="white")
        brand.pack(side="left", padx=(0, 28))
        self.login_logo = tk.Label(brand, text="Itelvino", bg="white", fg=self.NAVY, relief="groove")
        self.login_logo.pack()
        self.show_photo(self.login_logo, self.logo_path, "Itelvino", 220)
        content = tk.Frame(card, bg="white")
        content.pack(side="left", fill="y")
        tk.Label(content, text="ITELVINO ELETRÔNICOS", bg="white", fg=self.NAVY, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        if not self.db.has_user():
            tk.Label(content, text="Crie o usuário e a senha geral para começar.", bg="white", fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 16))
            self.auth_form(content, setup=True)
        else:
            tk.Label(content, text="Controle de estoque e vendas", bg="white", fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 16))
            self.auth_form(content, setup=False)
        mobile_text = f"Acesso pelo celular na mesma rede: {self.mobile_url}" if self.mobile_url else "Acesso móvel indisponível. Verifique a conexão de rede ou a porta 8765."
        tk.Label(content, text=mobile_text, bg="white", fg=self.BLUE, font=("Segoe UI", 9, "bold"), wraplength=320, justify="left").pack(anchor="w", pady=(14, 0))

    def auth_form(self, parent, setup):
        self.auth_user = tk.StringVar()
        self.auth_password = tk.StringVar()
        self.auth_confirm = tk.StringVar()
        tk.Label(parent, text="Usuário", bg="white", fg=self.TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        user = ttk.Entry(parent, textvariable=self.auth_user, width=36)
        user.pack(fill="x", pady=(4, 12))
        tk.Label(parent, text="Senha", bg="white", fg=self.TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        password = ttk.Entry(parent, textvariable=self.auth_password, show="•", width=36)
        password.pack(fill="x", pady=(4, 12))
        if setup:
            tk.Label(parent, text="Confirme a senha", bg="white", fg=self.TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
            ttk.Entry(parent, textvariable=self.auth_confirm, show="•", width=36).pack(fill="x", pady=(4, 14))
        button = ttk.Button(parent, text="Criar acesso" if setup else "Entrar", style="Accent.TButton", command=lambda: self.auth_submit(setup))
        button.pack(fill="x", pady=(7, 0))
        if not setup:
            actions = ttk.Frame(parent)
            actions.pack(fill="x", pady=(8, 0))
            ttk.Button(actions, text="Cadastrar usuário", command=self.open_user_dialog).pack(side="left", fill="x", expand=True, padx=(0, 4))
            ttk.Button(actions, text="Alterar senha", command=self.open_password_dialog).pack(side="left", fill="x", expand=True, padx=(4, 0))
        user.focus_set()
        self.root.bind("<Return>", lambda _event: self.auth_submit(setup))

    def auth_submit(self, setup):
        username, password = self.auth_user.get().strip(), self.auth_password.get()
        if not username or not password:
            messagebox.showwarning("Acesso", "Preencha usuário e senha.", parent=self.root)
            return
        if setup:
            if len(password) < 6:
                messagebox.showwarning("Acesso", "Use uma senha com pelo menos 6 caracteres.", parent=self.root)
                return
            if password != self.auth_confirm.get():
                messagebox.showwarning("Acesso", "As senhas não coincidem.", parent=self.root)
                return
            self.db.setup_user(username, password)
            messagebox.showinfo("Acesso criado", "Usuário configurado. Entre para abrir o sistema.", parent=self.root)
            self.show_auth()
        elif self.db.authenticate(username, password):
            self.root.unbind("<Return>")
            self.current_username = self.db.canonical_username(username)
            self.build_workspace(self.current_username)
        else:
            messagebox.showerror("Acesso", "Usuário ou senha incorretos.", parent=self.root)

    def open_user_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Cadastrar usuário")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        card = ttk.Frame(dialog, padding=22)
        card.pack(fill="both", expand=True)
        ttk.Label(card, text="Novo usuário", font=("Segoe UI", 15, "bold"), foreground=self.NAVY).pack(anchor="w", pady=(0, 12))
        fields = {}
        for label, key, secret in (("Nome de usuário", "username", False), ("Nova senha", "password", True), ("Confirme a senha", "confirm", True)):
            ttk.Label(card, text=label).pack(anchor="w")
            entry = ttk.Entry(card, width=34, show="•" if secret else "")
            entry.pack(fill="x", pady=(3, 10))
            fields[key] = entry

        def save_user():
            username = fields["username"].get().strip()
            password = fields["password"].get()
            if not username:
                messagebox.showwarning("Cadastro", "Informe o nome do usuário.", parent=dialog)
                return
            if len(password) < 6:
                messagebox.showwarning("Cadastro", "Use uma senha com pelo menos 6 caracteres.", parent=dialog)
                return
            if password != fields["confirm"].get():
                messagebox.showwarning("Cadastro", "As senhas não coincidem.", parent=dialog)
                return
            try:
                self.db.add_user(username, password)
            except ValueError as exc:
                messagebox.showwarning("Cadastro", str(exc), parent=dialog)
                return
            messagebox.showinfo("Cadastro", f"Usuário {username} cadastrado.", parent=dialog)
            dialog.destroy()

        ttk.Button(card, text="Salvar usuário", style="Accent.TButton", command=save_user).pack(fill="x", pady=(4, 0))
        def save_user_on_enter(_event=None):
            save_user()
            return "break"
        dialog.bind("<Return>", save_user_on_enter)
        dialog.grab_set()
        fields["username"].focus_set()

    def open_password_dialog(self, username=None):
        dialog = tk.Toplevel(self.root)
        dialog.title("Alterar senha")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        card = ttk.Frame(dialog, padding=22)
        card.pack(fill="both", expand=True)
        ttk.Label(card, text="Alterar senha", font=("Segoe UI", 15, "bold"), foreground=self.NAVY).pack(anchor="w", pady=(0, 12))
        fields = {}
        initial_username = username or getattr(self, "current_username", "") or self.auth_user.get()
        for label, key, secret in (("Nome de usuário", "username", False), ("Senha atual", "current", True), ("Nova senha", "new", True), ("Confirme a nova senha", "confirm", True)):
            ttk.Label(card, text=label).pack(anchor="w")
            entry = ttk.Entry(card, width=34, show="•" if secret else "")
            entry.pack(fill="x", pady=(3, 10))
            fields[key] = entry
        fields["username"].insert(0, initial_username)

        def save_password():
            account = fields["username"].get().strip()
            current = fields["current"].get()
            new_password = fields["new"].get()
            if not account or not current:
                messagebox.showwarning("Senha", "Informe usuário e senha atual.", parent=dialog)
                return
            if len(new_password) < 6:
                messagebox.showwarning("Senha", "Use uma nova senha com pelo menos 6 caracteres.", parent=dialog)
                return
            if new_password != fields["confirm"].get():
                messagebox.showwarning("Senha", "As novas senhas não coincidem.", parent=dialog)
                return
            try:
                self.db.change_password(account, current, new_password)
            except ValueError as exc:
                messagebox.showerror("Senha", str(exc), parent=dialog)
                return
            messagebox.showinfo("Senha", "Senha alterada com sucesso.", parent=dialog)
            dialog.destroy()

        ttk.Button(card, text="Salvar nova senha", style="Accent.TButton", command=save_password).pack(fill="x", pady=(4, 0))
        def save_password_on_enter(_event=None):
            save_password()
            return "break"
        dialog.bind("<Return>", save_password_on_enter)
        dialog.grab_set()
        fields["current"].focus_set()

    def clear_root(self):
        for child in self.root.winfo_children():
            child.destroy()

    def build_workspace(self, username):
        self.clear_root()
        header = tk.Frame(self.root, bg=self.NAVY, padx=22, pady=14)
        header.pack(fill="x")
        self.header_logo = tk.Label(header, text="ITV", bg=self.NAVY, fg="white")
        self.header_logo.pack(side="left", padx=(0, 14))
        self.show_photo(self.header_logo, self.logo_path, "ITV", 84)
        left = tk.Frame(header, bg=self.NAVY)
        left.pack(side="left")
        ttk.Label(left, text="ITELVINO ELETRÔNICOS", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Estoque e vendas", style="SubTitle.TLabel").pack(anchor="w", pady=(2, 0))
        account = tk.Frame(header, bg=self.NAVY)
        account.pack(side="right", anchor="e")
        tk.Label(account, text=f"Usuário: {username}", bg=self.NAVY, fg="#dbeafe", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 10))
        ttk.Button(account, text="Atualizar dados", style="Header.TButton", command=self.refresh_all).pack(side="left", padx=3)
        ttk.Button(account, text="Alterar senha", style="Header.TButton", command=lambda: self.open_password_dialog(username)).pack(side="left", padx=3)
        ttk.Button(account, text="Sair", style="Header.TButton", command=self.logout).pack(side="left", padx=(3, 0))
        body = ttk.Frame(self.root, padding=(18, 14, 18, 10))
        body.pack(fill="both", expand=True)
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill="both", expand=True)
        self.create_products_tab()
        self.create_stock_tab()
        self.create_sales_tab()
        self.create_reports_tab()
        footer = tk.Frame(self.root, bg="#e9edf4", padx=18, pady=7)
        footer.pack(fill="x", side="bottom")
        mobile_text = f"Celular na mesma rede: {self.mobile_url}" if self.mobile_url else "Acesso móvel indisponível (porta 8765)."
        tk.Label(footer, text=f"Dados locais  •  {datetime.now().strftime('%d/%m/%Y')}  •  {mobile_text}", bg="#e9edf4", fg=self.MUTED, font=("Segoe UI", 8)).pack(side="left")

    def logout(self):
        self.current_username = ""
        self.show_auth()

    def make_table(self, parent, columns, headings, widths=None, height=12, right_columns=()):
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
        for index, (column, heading) in enumerate(zip(columns, headings)):
            width = widths[index] if widths else 120
            tree.heading(column, text=heading)
            anchor = "e" if column in right_columns else ("w" if index in (0, 1) else "center")
            tree.column(column, width=width, anchor=anchor, stretch=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return frame, tree

    def create_products_tab(self):
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="Produtos")
        form = ttk.LabelFrame(tab, text="Cadastro de produto", padding=12)
        form.pack(fill="x", pady=(0, 12))
        self.prod_vars = {key: tk.StringVar() for key in ("barcode", "description", "cost", "price", "initial")}
        self.product_photo_path = None
        self.product_photo_is_new = False
        self.product_photo_cleared = True
        photo_box = ttk.Frame(form)
        photo_box.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 14))
        ttk.Label(photo_box, text="Foto do produto").pack(anchor="center", pady=(0, 4))
        self.product_photo_preview = tk.Label(photo_box, text="Sem foto", bg="#eef2f7", fg=self.MUTED, relief="groove")
        self.product_photo_preview.pack()
        ttk.Button(photo_box, text="Escolher foto", command=self.choose_product_photo).pack(fill="x", pady=(5, 2))
        ttk.Button(photo_box, text="Remover foto", command=self.remove_product_photo).pack(fill="x")
        fields = [("Código de barras", "barcode"), ("Descrição", "description"), ("Preço de custo (R$)", "cost"), ("Preço de venda (R$)", "price"), ("Estoque inicial", "initial")]
        for col, (label, key) in enumerate(fields):
            box = ttk.Frame(form)
            box.grid(row=0, column=col + 1, sticky="ew", padx=(0 if col == 0 else 10, 0))
            ttk.Label(box, text=label).pack(anchor="w", pady=(0, 4))
            align = "right" if key in ("barcode", "cost", "price", "initial") else "left"
            ttk.Entry(box, textvariable=self.prod_vars[key], justify=align).pack(fill="x")
            form.columnconfigure(col + 1, weight=1)
        self.prod_hint = ttk.Label(form, text="", foreground=self.MUTED)
        self.prod_hint.grid(row=1, column=1, columnspan=3, sticky="w", pady=(9, 0))
        actions = ttk.Frame(form)
        actions.grid(row=1, column=4, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(actions, text="Limpar", command=self.clear_product_form).pack(side="left", padx=4)
        ttk.Button(actions, text="Salvar produto", style="Accent.TButton", command=self.save_product).pack(side="left", padx=4)
        search_row = ttk.Frame(tab)
        search_row.pack(fill="x", pady=(0, 7))
        ttk.Label(search_row, text="Buscar produto:").pack(side="left")
        self.product_search = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.product_search, width=34)
        search_entry.pack(side="left", padx=8)
        search_entry.bind("<KeyRelease>", lambda _e: self.refresh_products())
        ttk.Label(search_row, text="Selecione um item para editar seus dados.", foreground=self.MUTED).pack(side="right")
        table_frame, self.products_tree = self.make_table(tab, ("barcode", "description", "quantity", "cost", "price"), ("Código de barras", "Descrição", "Estoque", "Custo", "Venda"), (160, 360, 90, 120, 120), 12, ("barcode", "quantity", "cost", "price"))
        table_frame.pack(fill="both", expand=True)
        self.products_tree.bind("<<TreeviewSelect>>", self.select_product)
        self.refresh_products()

    def clear_product_form(self):
        self.edit_product_id = None
        for var in self.prod_vars.values():
            var.set("")
        self.product_photo_path = None
        self.product_photo_is_new = False
        self.product_photo_cleared = True
        self.show_photo(self.product_photo_preview, None)
        self.prod_hint.configure(text="Produto novo: o estoque inicial será registrado como entrada.")
        self.products_tree.selection_remove(self.products_tree.selection())

    def choose_product_photo(self):
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Escolher foto do produto",
            filetypes=(("Imagens", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff"), ("Todos os arquivos", "*.*")),
        )
        if not selected:
            return
        self.product_photo_path = selected
        self.product_photo_is_new = True
        self.product_photo_cleared = False
        self.show_photo(self.product_photo_preview, selected, "Foto inválida", 220)

    def remove_product_photo(self):
        self.product_photo_path = None
        self.product_photo_is_new = False
        self.product_photo_cleared = True
        self.show_photo(self.product_photo_preview, None)

    def select_product(self, _event=None):
        selected = self.products_tree.selection()
        if not selected:
            return
        row = self.db.product(int(selected[0]))
        if row:
            self.edit_product_id = row["id"]
            self.prod_vars["barcode"].set(row["barcode"])
            self.prod_vars["description"].set(row["description"])
            self.prod_vars["cost"].set(f"{row['cost']:.2f}".replace(".", ","))
            self.prod_vars["price"].set(f"{row['price']:.2f}".replace(".", ","))
            self.prod_vars["initial"].set("")
            self.product_photo_path = row["photo_path"]
            self.product_photo_is_new = False
            self.product_photo_cleared = False
            self.show_photo(self.product_photo_preview, self.product_photo_path, max_side=220)
            self.prod_hint.configure(text=f"Editando produto. Estoque atual: {row['quantity']} un. Para alterar o saldo, use a aba Estoque.")

    def save_product(self):
        barcode = self.prod_vars["barcode"].get().strip()
        description = self.prod_vars["description"].get().strip()
        try:
            cost, price = parse_money(self.prod_vars["cost"].get()), parse_money(self.prod_vars["price"].get())
            initial = int(self.prod_vars["initial"].get().strip() or "0") if not getattr(self, "edit_product_id", None) else 0
            if initial < 0:
                raise ValueError("O estoque inicial não pode ser negativo.")
            if not barcode or not description:
                raise ValueError("Preencha código de barras e descrição.")
            photo_path = self.product_photo_path
            if self.product_photo_is_new and photo_path:
                source = Path(photo_path)
                image_dir = data_directory() / "product_images"
                image_dir.mkdir(parents=True, exist_ok=True)
                stored_image = image_dir / f"{uuid.uuid4().hex}{source.suffix.lower()}"
                shutil.copy2(source, stored_image)
                photo_path = str(stored_image)
            elif self.product_photo_cleared:
                photo_path = None
            self.db.save_product(getattr(self, "edit_product_id", None), barcode, description, cost, price, initial, photo_path, self.current_username)
        except sqlite3.IntegrityError:
            messagebox.showerror("Produto", "Já existe um produto cadastrado com esse código de barras.", parent=self.root)
            return
        except (ValueError, OverflowError) as exc:
            messagebox.showwarning("Produto", str(exc) or "Confira os valores informados.", parent=self.root)
            return
        except OSError as exc:
            messagebox.showerror("Foto do produto", f"Não foi possível salvar a imagem escolhida.\n{exc}", parent=self.root)
            return
        self.clear_product_form()
        self.refresh_all()
        messagebox.showinfo("Produto", "Produto salvo.", parent=self.root)

    def refresh_products(self):
        if not hasattr(self, "products_tree"):
            return
        for item in self.products_tree.get_children():
            self.products_tree.delete(item)
        for row in self.db.products(self.product_search.get() if hasattr(self, "product_search") else ""):
            self.products_tree.insert("", "end", iid=str(row["id"]), values=(row["barcode"], row["description"], row["quantity"], money(row["cost"]), money(row["price"])))

    def create_stock_tab(self):
        tab = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(tab, text="Movimentações")
        intro = ttk.Label(tab, text="Registre entradas e saídas; o histórico completo aparece abaixo.", foreground=self.MUTED)
        intro.pack(anchor="w", pady=(0, 12))
        form = ttk.LabelFrame(tab, text="Movimentar estoque", padding=16)
        form.pack(fill="x", anchor="n")
        self.stock_kind = tk.StringVar(value="Entrada")
        self.stock_product = tk.StringVar()
        self.stock_qty = tk.StringVar()
        self.stock_cost = tk.StringVar()
        self.stock_note = tk.StringVar()
        fields = [(1, "Tipo", self.stock_kind, ("Entrada", "Saída manual")), (2, "Produto (digite para buscar)", self.stock_product, None), (3, "Quantidade", self.stock_qty, None), (4, "Custo unitário (R$)", self.stock_cost, None), (5, "Observação / fornecedor", self.stock_note, None)]
        for col, label, variable, values in fields:
            box = ttk.Frame(form)
            box.grid(row=0, column=col, sticky="ew", padx=(10, 0))
            ttk.Label(box, text=label).pack(anchor="w", pady=(0, 4))
            if values:
                control = ttk.Combobox(box, textvariable=variable, values=values, state="readonly")
                control.bind("<<ComboboxSelected>>", lambda _e: self.stock_type_changed())
            elif variable is self.stock_product:
                control = ttk.Combobox(box, textvariable=variable, state="normal")
                self.stock_product_widget = control
                control.bind("<KeyRelease>", self.filter_stock_choices)
                control.bind("<<ComboboxSelected>>", self.stock_product_selected)
                control.bind("<Return>", self.stock_product_enter)
            else:
                control = ttk.Entry(box, textvariable=variable, justify="right" if variable in (self.stock_qty, self.stock_cost) else "left")
                if variable is self.stock_qty:
                    self.stock_qty_widget = control
            control.pack(fill="x")
            form.columnconfigure(col, weight=1)
        photo_box = ttk.Frame(form)
        photo_box.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 14))
        ttk.Label(photo_box, text="Produto selecionado").pack(anchor="center", pady=(0, 4))
        self.stock_photo_preview = tk.Label(photo_box, text="—", bg="#eef2f7", fg=self.MUTED, relief="groove")
        self.stock_photo_preview.pack()
        ttk.Button(form, text="Registrar movimentação", style="Accent.TButton", command=self.save_stock_movement).grid(row=1, column=4, columnspan=2, sticky="e", pady=(14, 0))
        self.stock_status = ttk.Label(form, text="As entradas atualizam o custo cadastrado do produto.", foreground=self.MUTED)
        self.stock_status.grid(row=1, column=1, columnspan=3, sticky="w", pady=(14, 0))
        history = ttk.LabelFrame(tab, text="Histórico completo de movimentações", padding=8)
        history.pack(fill="both", expand=True, pady=(12, 0))
        frame, self.stock_history_tree = self.make_table(
            history,
            ("date", "kind", "barcode", "description", "quantity", "unit_cost", "value", "username", "reference"),
            ("Data e hora", "Tipo", "Código", "Produto", "Qtd.", "Custo un.", "Valor", "Usuário", "Observação / venda"),
            (140, 95, 110, 190, 60, 90, 100, 130, 180),
            10,
            ("barcode", "quantity", "unit_cost", "value"),
        )
        frame.pack(fill="both", expand=True)
        self.refresh_stock_products()
        self.refresh_stock_history()

    def stock_type_changed(self):
        entry = self.stock_kind.get() == "Entrada"
        self.stock_status.configure(text="As entradas atualizam o custo cadastrado do produto." if entry else "A saída manual não pode exceder o saldo atual.")

    def refresh_stock_products(self):
        rows = self.db.products()
        self.stock_product_map = {f"{r['barcode']} — {r['description']} (saldo: {r['quantity']})": r for r in rows}
        self.sale_product_map = self.stock_product_map
        if hasattr(self, "stock_product_widget"):
            self.stock_product_widget.configure(values=list(self.stock_product_map.keys()))
        if hasattr(self, "sale_product_widget"):
            self.sale_product_widget.configure(values=list(self.sale_product_map.keys()))

    def selected_stock_product(self):
        key = self.stock_product.get()
        return self.stock_product_map.get(key)

    def filter_stock_choices(self, _event=None):
        query = self.stock_product.get().casefold().strip()
        choices = [key for key in self.stock_product_map if query in key.casefold()] if query else list(self.stock_product_map)
        self.stock_product_widget.configure(values=choices)
        product = self.selected_stock_product()
        self.show_photo(self.stock_photo_preview, product["photo_path"] if product else None, "—", 220)

    def stock_product_selected(self, _event=None):
        product = self.selected_stock_product()
        if product:
            self.show_photo(self.stock_photo_preview, product["photo_path"], "—", 220)
            self.stock_cost.set(f"{product['cost']:.2f}".replace(".", ","))

    def stock_product_enter(self, _event=None):
        key = self.stock_product.get()
        if not key.strip():
            return "break"
        if key not in self.stock_product_map:
            matches = [name for name in self.stock_product_map if key.casefold().strip() in name.casefold()]
            if len(matches) != 1:
                return "break"
            key = matches[0]
            self.stock_product.set(key)
        self.stock_product_selected()
        self.stock_qty_widget.focus_set()
        return "break"

    def save_stock_movement(self):
        product = self.selected_stock_product()
        try:
            qty = int(self.stock_qty.get().strip())
            if qty <= 0:
                raise ValueError("A quantidade deve ser maior que zero.")
            if not product:
                raise ValueError("Selecione um produto.")
            cost_text = self.stock_cost.get().strip()
            cost = parse_money(cost_text) if cost_text else float(product["cost"])
            self.db.stock_movement(product["id"], self.stock_kind.get(), qty, cost, self.stock_note.get().strip(), self.current_username)
        except (ValueError, sqlite3.IntegrityError) as exc:
            messagebox.showwarning("Estoque", str(exc), parent=self.root)
            return
        self.stock_product.set("")
        self.stock_qty.set("")
        self.stock_cost.set("")
        self.stock_note.set("")
        self.show_photo(self.stock_photo_preview, None, "—", 220)
        self.refresh_all()
        messagebox.showinfo("Estoque", "Movimentação registrada.", parent=self.root)

    def refresh_stock_history(self):
        if not hasattr(self, "stock_history_tree"):
            return
        for row in self.stock_history_tree.get_children():
            self.stock_history_tree.delete(row)
        for movement in self.db.movement_history():
            self.stock_history_tree.insert(
                "",
                "end",
                values=(
                    datetime.strptime(movement["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M"),
                    movement["kind"],
                    movement["barcode"],
                    movement["description"],
                    movement["quantity"],
                    money(movement["unit_cost"]),
                    money(movement["movement_value"]),
                    movement["username"],
                    movement["reference"],
                ),
            )

    def create_sales_tab(self):
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="Vendas")
        entry_row = ttk.LabelFrame(tab, text="Adicionar produto à venda", padding=10)
        entry_row.pack(fill="x", pady=(0, 10))
        self.sale_barcode = tk.StringVar()
        self.sale_product = tk.StringVar()
        ttk.Label(entry_row, text="Código de barras (leitor ou digitação)").grid(row=0, column=1, sticky="w")
        self.sale_barcode_widget = ttk.Entry(entry_row, textvariable=self.sale_barcode, width=28, justify="right")
        self.sale_barcode_widget.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(4, 0))
        self.sale_barcode_widget.bind("<Return>", lambda _e: self.add_to_cart(by_barcode=True))
        ttk.Label(entry_row, text="Ou digite o nome/código para buscar").grid(row=0, column=2, sticky="w")
        self.sale_product_widget = ttk.Combobox(entry_row, textvariable=self.sale_product, state="normal", width=48)
        self.sale_product_widget.grid(row=1, column=2, sticky="ew", padx=(0, 10), pady=(4, 0))
        self.sale_product_widget.bind("<KeyRelease>", self.filter_sale_choices)
        self.sale_product_widget.bind("<<ComboboxSelected>>", self.sale_product_selected)
        self.sale_product_widget.bind("<Return>", self.sale_product_enter)
        photo_box = ttk.Frame(entry_row)
        photo_box.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 14))
        ttk.Label(photo_box, text="Produto selecionado").pack(anchor="center", pady=(0, 4))
        self.sale_photo_preview = tk.Label(photo_box, text="—", bg="#eef2f7", fg=self.MUTED, relief="groove")
        self.sale_photo_preview.pack()
        ttk.Button(entry_row, text="Adicionar", style="Accent.TButton", command=lambda: self.add_to_cart()).grid(row=1, column=3, sticky="e", pady=(4, 0))
        entry_row.columnconfigure(1, weight=1)
        entry_row.columnconfigure(2, weight=2)
        cart_box = ttk.LabelFrame(tab, text="Itens da venda", padding=9)
        cart_box.pack(fill="both", expand=True)
        table_frame, self.cart_tree = self.make_table(cart_box, ("barcode", "description", "qty", "unit", "total"), ("Código", "Produto", "Qtd.", "Preço un.", "Total"), (140, 390, 75, 110, 120), 8, ("barcode", "qty", "unit", "total"))
        table_frame.pack(fill="both", expand=True)
        actions = ttk.Frame(cart_box)
        actions.pack(fill="x", pady=(7, 2))
        ttk.Button(actions, text="− 1 unidade", command=lambda: self.change_cart_qty(-1)).pack(side="left", padx=(0, 5))
        ttk.Button(actions, text="+ 1 unidade", command=lambda: self.change_cart_qty(1)).pack(side="left", padx=5)
        ttk.Button(actions, text="Remover item", command=self.remove_cart_item).pack(side="left", padx=5)
        checkout = ttk.LabelFrame(tab, text="Pagamento", padding=10)
        checkout.pack(fill="x", pady=(10, 0))
        self.discount_var = tk.StringVar(value="0")
        self.payment_var = tk.StringVar(value="Dinheiro")
        self.installments_var = tk.StringVar(value="1")
        ttk.Label(checkout, text="Desconto (%)").grid(row=0, column=0, sticky="w")
        discount_entry = ttk.Entry(checkout, textvariable=self.discount_var, width=10, justify="right")
        discount_entry.grid(row=1, column=0, sticky="w", padx=(0, 14), pady=(4, 0))
        discount_entry.bind("<KeyRelease>", lambda _e: self.refresh_cart())
        ttk.Label(checkout, text="Forma de pagamento").grid(row=0, column=1, sticky="w")
        ttk.Combobox(checkout, textvariable=self.payment_var, values=("Dinheiro", "PIX", "Cartão de débito", "Cartão de crédito", "Outro"), state="readonly", width=20).grid(row=1, column=1, sticky="w", padx=(0, 14), pady=(4, 0))
        ttk.Label(checkout, text="Parcelas (1 = à vista)").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(checkout, from_=1, to=48, textvariable=self.installments_var, width=8, justify="right").grid(row=1, column=2, sticky="w", padx=(0, 20), pady=(4, 0))
        self.sale_totals = ttk.Label(checkout, text="Subtotal: R$ 0,00   •   Desconto: R$ 0,00   •   Total: R$ 0,00", font=("Segoe UI", 10, "bold"), foreground=self.NAVY)
        self.sale_totals.grid(row=1, column=3, sticky="e", pady=(4, 0))
        ttk.Button(checkout, text="Concluir venda", style="Accent.TButton", command=self.finish_sale).grid(row=1, column=4, sticky="e", padx=(12, 0), pady=(4, 0))
        checkout.columnconfigure(3, weight=1)
        self.cart = {}
        self.refresh_stock_products()
        self.refresh_cart()

    def add_to_cart(self, by_barcode=False):
        barcode = self.sale_barcode.get().strip()
        product = self.db.by_barcode(barcode) if barcode else None
        if not product and not barcode and not by_barcode:
            product = self.sale_product_map.get(self.sale_product.get())
        if not product:
            messagebox.showwarning("Venda", "Informe um código de barras cadastrado ou escolha um produto da lista filtrada.", parent=self.root)
            self.sale_barcode_widget.focus_set()
            return
        quantity = simpledialog.askinteger("Quantidade", f"Quantas unidades de {product['description']}?", parent=self.root, initialvalue=1, minvalue=1)
        if quantity is None:
            return
        current = self.cart.get(product["id"], {}).get("qty", 0)
        if current + quantity > product["quantity"]:
            messagebox.showwarning("Estoque", f"Estoque insuficiente. Saldo de {product['description']}: {product['quantity']}.", parent=self.root)
            return
        if product["id"] not in self.cart:
            self.cart[product["id"]] = {"id": product["id"], "barcode": product["barcode"], "description": product["description"], "price": product["price"], "qty": 0}
        self.cart[product["id"]]["qty"] += quantity
        self.sale_barcode.set("")
        self.sale_product.set("")
        self.show_photo(self.sale_photo_preview, None, "—", 220)
        self.refresh_cart()
        self.sale_barcode_widget.focus_set()

    def filter_sale_choices(self, _event=None):
        query = self.sale_product.get().casefold().strip()
        choices = [key for key in self.sale_product_map if query in key.casefold()] if query else list(self.sale_product_map)
        self.sale_product_widget.configure(values=choices)
        product = self.sale_product_map.get(self.sale_product.get())
        self.show_photo(self.sale_photo_preview, product["photo_path"] if product else None, "—", 220)

    def sale_product_selected(self, _event=None):
        product = self.sale_product_map.get(self.sale_product.get())
        self.show_photo(self.sale_photo_preview, product["photo_path"] if product else None, "—", 220)

    def sale_product_enter(self, _event=None):
        key = self.sale_product.get()
        if not key.strip():
            return "break"
        if key not in self.sale_product_map:
            matches = [name for name in self.sale_product_map if key.casefold().strip() in name.casefold()]
            if len(matches) != 1:
                return "break"
            key = matches[0]
            self.sale_product.set(key)
        self.sale_product_selected()
        self.add_to_cart()
        return "break"

    def selected_cart_id(self):
        selection = self.cart_tree.selection()
        return int(selection[0]) if selection else None

    def change_cart_qty(self, delta):
        product_id = self.selected_cart_id()
        if not product_id:
            return
        item = self.cart[product_id]
        new_qty = item["qty"] + delta
        stock = self.db.product(product_id)["quantity"]
        if new_qty > stock:
            messagebox.showwarning("Estoque", "A quantidade da venda não pode exceder o saldo em estoque.", parent=self.root)
            return
        if new_qty <= 0:
            self.cart.pop(product_id)
        else:
            item["qty"] = new_qty
        self.refresh_cart()

    def remove_cart_item(self):
        product_id = self.selected_cart_id()
        if product_id:
            self.cart.pop(product_id, None)
            self.refresh_cart()

    def refresh_cart(self):
        if not hasattr(self, "cart_tree"):
            return
        for row in self.cart_tree.get_children():
            self.cart_tree.delete(row)
        for product_id, item in self.cart.items():
            self.cart_tree.insert("", "end", iid=str(product_id), values=(item["barcode"], item["description"], item["qty"], money(item["price"]), money(item["qty"] * item["price"])))
        subtotal = sum(item["qty"] * item["price"] for item in self.cart.values())
        try:
            discount_pct = float(self.discount_var.get().strip().replace(",", ".") or 0)
        except ValueError:
            discount_pct = 0
        discount = subtotal * max(0, min(100, discount_pct)) / 100
        self.sale_totals.configure(text=f"Subtotal: {money(subtotal)}   •   Desconto: {money(discount)}   •   Total: {money(subtotal - discount)}")

    def finish_sale(self):
        if not self.cart:
            messagebox.showwarning("Venda", "Adicione ao menos um produto.", parent=self.root)
            return
        try:
            discount = float(self.discount_var.get().strip().replace(",", ".") or 0)
            if not 0 <= discount <= 100:
                raise ValueError("O desconto deve ficar entre 0 e 100%.")
            installments = int(self.installments_var.get())
            if not 1 <= installments <= 48:
                raise ValueError("Informe de 1 a 48 parcelas.")
            sale_id, subtotal, discount_value, total = self.db.complete_sale(list(self.cart.values()), discount, self.payment_var.get(), installments, self.current_username)
        except (ValueError, sqlite3.IntegrityError) as exc:
            messagebox.showwarning("Venda", str(exc), parent=self.root)
            return
        self.cart.clear()
        self.discount_var.set("0")
        self.installments_var.set("1")
        self.refresh_all()
        self.tabs.select(3)
        self.daily_date.set(datetime.now().strftime("%d/%m/%Y"))
        self.refresh_daily_report()
        messagebox.showinfo("Venda concluída", f"Venda #{sale_id} registrada.\n\nSubtotal: {money(subtotal)}\nDesconto: {money(discount_value)}\nTotal: {money(total)}", parent=self.root)

    def create_reports_tab(self):
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="Relatórios")
        self.report_tabs = ttk.Notebook(tab)
        self.report_tabs.pack(fill="both", expand=True)
        daily = ttk.Frame(self.report_tabs, padding=12)
        monthly = ttk.Frame(self.report_tabs, padding=12)
        movements = ttk.Frame(self.report_tabs, padding=12)
        self.report_tabs.add(daily, text="Vendas do dia")
        self.report_tabs.add(monthly, text="Resumo mensal")
        self.report_tabs.add(movements, text="Estoque no mês")
        self.daily_date = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.month_value = tk.StringVar(value=datetime.now().strftime("%m/%Y"))

        date_row = ttk.Frame(daily)
        date_row.pack(fill="x", pady=(0, 8))
        ttk.Label(date_row, text="Data (DD/MM/YYYY)").pack(side="left")
        ttk.Button(date_row, text="◀", width=3, command=lambda: self.shift_daily_date(-1)).pack(side="left", padx=(8, 2))
        ttk.Entry(date_row, textvariable=self.daily_date, width=14, justify="right").pack(side="left", padx=8)
        ttk.Button(date_row, text="▶", width=3, command=lambda: self.shift_daily_date(1)).pack(side="left", padx=(0, 8))
        daily_filters = ttk.LabelFrame(daily, text="Filtros", style="Filter.TLabelframe", padding=(10, 6))
        daily_filters.pack(fill="x", pady=(0, 8))
        self.daily_sale_filter = tk.StringVar()
        self.daily_item_filter = tk.StringVar()
        ttk.Label(daily_filters, text="Número da venda").pack(side="left")
        ttk.Entry(daily_filters, textvariable=self.daily_sale_filter, width=12, justify="right").pack(side="left", padx=(6, 14))
        ttk.Label(daily_filters, text="Item (nome ou código)").pack(side="left")
        ttk.Entry(daily_filters, textvariable=self.daily_item_filter, width=30).pack(side="left", padx=(6, 14))
        ttk.Button(daily_filters, text="Aplicar filtros", style="Accent.TButton", command=self.refresh_daily_report).pack(side="left", padx=(0, 6))
        ttk.Button(daily_filters, text="Limpar", command=self.clear_daily_filters).pack(side="left")
        self.daily_summary = ttk.Label(daily, text="", font=("Segoe UI", 10, "bold"), foreground=self.NAVY, wraplength=1050, justify="left")
        self.daily_summary.pack(anchor="w", pady=(0, 6))
        self.daily_payment_summary = ttk.Label(daily, text="", foreground=self.MUTED, wraplength=1050, justify="left")
        self.daily_payment_summary.pack(anchor="w", pady=(0, 7))
        frame, self.daily_tree = self.make_table(daily, ("id", "time", "username", "items", "subtotal", "discount", "total", "payment", "installments"), ("Venda", "Horário", "Usuário", "Itens da venda", "Subtotal", "Desconto", "Total", "Pagamento", "Parcelas"), (65, 75, 105, 220, 95, 85, 95, 120, 70), 10, ("subtotal", "discount", "total", "installments"))
        frame.pack(fill="both", expand=True)

        month_sales_row = ttk.Frame(monthly)
        month_sales_row.pack(fill="x", pady=(0, 8))
        ttk.Label(month_sales_row, text="Mês (MM/AAAA)").pack(side="left")
        ttk.Button(month_sales_row, text="◀", width=3, command=lambda: self.shift_report_month(-1)).pack(side="left", padx=(8, 2))
        ttk.Entry(month_sales_row, textvariable=self.month_value, width=12, justify="right").pack(side="left", padx=8)
        ttk.Button(month_sales_row, text="▶", width=3, command=lambda: self.shift_report_month(1)).pack(side="left", padx=(0, 8))
        month_sales_filters = ttk.LabelFrame(monthly, text="Filtros das vendas", style="Filter.TLabelframe", padding=(10, 6))
        month_sales_filters.pack(fill="x", pady=(0, 8))
        self.month_sale_filter = tk.StringVar()
        self.month_item_filter = tk.StringVar()
        ttk.Label(month_sales_filters, text="Número da venda").pack(side="left")
        ttk.Entry(month_sales_filters, textvariable=self.month_sale_filter, width=12, justify="right").pack(side="left", padx=(6, 14))
        ttk.Label(month_sales_filters, text="Item (nome ou código)").pack(side="left")
        ttk.Entry(month_sales_filters, textvariable=self.month_item_filter, width=30).pack(side="left", padx=(6, 14))
        ttk.Button(month_sales_filters, text="Aplicar filtros", style="Accent.TButton", command=self.refresh_month_report).pack(side="left", padx=(0, 6))
        ttk.Button(month_sales_filters, text="Limpar", command=self.clear_month_sales_filters).pack(side="left")
        self.month_summary = ttk.Label(monthly, text="", font=("Segoe UI", 10, "bold"), foreground=self.NAVY, wraplength=1050, justify="left")
        self.month_summary.pack(anchor="w", pady=(0, 5))
        self.month_methods = ttk.Label(monthly, text="", foreground=self.MUTED, wraplength=1050, justify="left")
        self.month_methods.pack(anchor="w", pady=(0, 5))
        self.month_cost_note = ttk.Label(monthly, text="", foreground=self.MUTED, wraplength=1050, justify="left")
        self.month_cost_note.pack(anchor="w", pady=(0, 6))
        frame, self.month_sales_tree = self.make_table(monthly, ("id", "time", "username", "items", "subtotal", "discount", "total", "payment", "installments"), ("Venda", "Data e hora", "Usuário", "Itens da venda", "Subtotal", "Desconto", "Total", "Pagamento", "Parcelas"), (65, 125, 105, 220, 95, 85, 95, 120, 70), 7, ("subtotal", "discount", "total", "installments"))
        frame.pack(fill="both", expand=True)

        movement_month_row = ttk.Frame(movements)
        movement_month_row.pack(fill="x", pady=(0, 8))
        ttk.Label(movement_month_row, text="Mês (MM/AAAA)").pack(side="left")
        ttk.Button(movement_month_row, text="◀", width=3, command=lambda: self.shift_report_month(-1)).pack(side="left", padx=(8, 2))
        ttk.Entry(movement_month_row, textvariable=self.month_value, width=12, justify="right").pack(side="left", padx=8)
        ttk.Button(movement_month_row, text="▶", width=3, command=lambda: self.shift_report_month(1)).pack(side="left", padx=(0, 8))
        movement_filters = ttk.LabelFrame(movements, text="Filtros de movimentação", style="Filter.TLabelframe", padding=(10, 6))
        movement_filters.pack(fill="x", pady=(0, 8))
        self.movement_kind_filter = tk.StringVar(value="Todos")
        self.movement_sale_filter = tk.StringVar()
        self.movement_item_filter = tk.StringVar()
        ttk.Label(movement_filters, text="Tipo").pack(side="left")
        ttk.Combobox(movement_filters, textvariable=self.movement_kind_filter, values=("Todos", "Entradas", "Saídas"), state="readonly", width=11).pack(side="left", padx=(6, 14))
        ttk.Label(movement_filters, text="Número da venda").pack(side="left")
        ttk.Entry(movement_filters, textvariable=self.movement_sale_filter, width=11, justify="right").pack(side="left", padx=(6, 14))
        ttk.Label(movement_filters, text="Item (nome ou código)").pack(side="left")
        ttk.Entry(movement_filters, textvariable=self.movement_item_filter, width=25).pack(side="left", padx=(6, 10))
        ttk.Button(movement_filters, text="Aplicar filtros", style="Accent.TButton", command=self.refresh_movement_report).pack(side="left", padx=(0, 6))
        ttk.Button(movement_filters, text="Limpar", command=self.clear_movement_filters).pack(side="left")
        self.movement_summary = ttk.Label(movements, text="", font=("Segoe UI", 10, "bold"), foreground=self.NAVY, wraplength=1050, justify="left")
        self.movement_summary.pack(anchor="w", pady=(0, 7))
        frame, self.movement_tree = self.make_table(movements, ("date", "kind", "sale", "barcode", "description", "quantity", "cost", "username", "reference"), ("Data e hora", "Movimento", "Venda", "Código", "Produto", "Qtd.", "Custo un.", "Usuário", "Referência / observação"), (125, 105, 65, 100, 185, 55, 90, 100, 200), 9, ("quantity", "cost"))
        frame.pack(fill="both", expand=True)
        self.refresh_daily_report()
        self.refresh_month_report()
        self.refresh_movement_report()

    def clear_daily_filters(self):
        self.daily_sale_filter.set("")
        self.daily_item_filter.set("")
        self.refresh_daily_report()

    def clear_month_sales_filters(self):
        self.month_sale_filter.set("")
        self.month_item_filter.set("")
        self.refresh_month_report()

    def clear_movement_filters(self):
        self.movement_kind_filter.set("Todos")
        self.movement_sale_filter.set("")
        self.movement_item_filter.set("")
        self.refresh_movement_report()

    @staticmethod
    def normalize_sale_filter(value):
        value = value.strip().lstrip("#").strip()
        if not value:
            return ""
        if not value.isdigit():
            raise ValueError("O número da venda deve conter apenas números (o # é opcional).")
        return str(int(value))

    def shift_daily_date(self, days):
        try:
            current = datetime.strptime(self.daily_date.get().strip(), "%d/%m/%Y")
        except ValueError:
            current = datetime.now()
        self.daily_date.set((current + timedelta(days=days)).strftime("%d/%m/%Y"))
        self.refresh_daily_report()

    def shift_report_month(self, offset):
        try:
            current = datetime.strptime(self.month_value.get().strip(), "%m/%Y")
        except ValueError:
            current = datetime.now()
        month_index = current.year * 12 + current.month - 1 + offset
        year, month_zero = divmod(month_index, 12)
        self.month_value.set(datetime(year, month_zero + 1, 1).strftime("%m/%Y"))
        self.refresh_month_reports()

    def refresh_month_reports(self):
        self.refresh_month_report()
        self.refresh_movement_report()

    def refresh_daily_report(self):
        if not hasattr(self, "daily_tree"):
            return
        displayed_day = self.daily_date.get().strip()
        try:
            day = datetime.strptime(displayed_day, "%d/%m/%Y")
            iso_day = day.strftime("%Y-%m-%d")
        except ValueError:
            messagebox.showwarning("Relatório", "Use o formato DD/MM/YYYY para a data.", parent=self.root)
            return
        try:
            sale_number = self.normalize_sale_filter(self.daily_sale_filter.get())
        except ValueError as exc:
            messagebox.showwarning("Relatório", str(exc), parent=self.root)
            return
        sales, sums, summary, items = self.db.daily_sales(iso_day, sale_number, self.daily_item_filter.get().strip())
        for row in self.daily_tree.get_children():
            self.daily_tree.delete(row)
        for sale in sales:
            self.daily_tree.insert("", "end", values=(f"#{sale['id']}", sale["created_at"][11:16], sale["username"], sale["item_list"] or "—", money(sale["subtotal"]), money(sale["discount_value"]), money(sale["total"]), sale["payment_method"], sale["installments"]))
        breakdown = "  •  ".join(f"{r['payment_method']}: {money(r['total'] or 0)} ({r['amount']})" for r in sums) or "Sem vendas"
        self.daily_summary.configure(text=f"{displayed_day}   |   Vendas: {summary['sale_count']}   |   Itens: {items['quantity']}   |   Venda bruta: {money(summary['subtotal'])}   |   Descontos: {money(summary['discount'])}   |   Total vendido: {money(summary['total'])}   |   Investido nos itens: {money(items['invested'])}")
        note = f"Custo não registrado para {items['unknown_cost_quantity']} unidade(s) de vendas antigas." if items["unknown_cost_quantity"] else ""
        self.daily_payment_summary.configure(text=f"Pagamentos: {breakdown}" + (f"   •   {note}" if note else ""))

    def refresh_month_report(self):
        if not hasattr(self, "month_summary"):
            return
        displayed_month = self.month_value.get().strip()
        try:
            month = datetime.strptime(displayed_month, "%m/%Y").strftime("%Y-%m")
        except ValueError:
            messagebox.showwarning("Relatório", "Use o formato MM/AAAA para o mês.", parent=self.root)
            return
        try:
            sale_number = self.normalize_sale_filter(self.month_sale_filter.get())
        except ValueError as exc:
            messagebox.showwarning("Relatório", str(exc), parent=self.root)
            return
        summary, item_summary, methods, sales = self.db.monthly_sales(month, sale_number, self.month_item_filter.get().strip())
        difference_label = "Diferença estimada (parcial)" if item_summary["unknown_cost_quantity"] else "Diferença estimada"
        self.month_summary.configure(text=f"{displayed_month}\nVendas: {summary['count']}  •  Itens vendidos: {item_summary['quantity']}  •  Venda bruta: {money(summary['subtotal'])}  •  Descontos: {money(summary['discount'])}\nTotal vendido: {money(summary['total'])}  •  Investido nos itens: {money(item_summary['invested'])}  •  {difference_label}: {money(summary['total'] - item_summary['invested'])}")
        self.month_methods.configure(text="   •   ".join(f"{r['payment_method']}: {money(r['total'])} ({r['count']} venda(s))" for r in methods) or "Nenhuma venda no mês.")
        self.month_cost_note.configure(text=f"Custo não registrado para {item_summary['unknown_cost_quantity']} unidade(s) de vendas antigas." if item_summary["unknown_cost_quantity"] else "Investimento calculado com o custo do produto registrado no momento da venda.")
        for row in self.month_sales_tree.get_children():
            self.month_sales_tree.delete(row)
        for sale in sales:
            sale_date = datetime.strptime(sale["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
            self.month_sales_tree.insert("", "end", values=(f"#{sale['id']}", sale_date, sale["username"], sale["item_list"] or "—", money(sale["subtotal"]), money(sale["discount_value"]), money(sale["total"]), sale["payment_method"], sale["installments"]))

    def refresh_movement_report(self):
        if not hasattr(self, "movement_tree"):
            return
        displayed_month = self.month_value.get().strip()
        try:
            month = datetime.strptime(displayed_month, "%m/%Y").strftime("%Y-%m")
        except ValueError:
            messagebox.showwarning("Relatório", "Use o formato MM/AAAA para o mês.", parent=self.root)
            return
        try:
            sale_number = self.normalize_sale_filter(self.movement_sale_filter.get())
        except ValueError as exc:
            messagebox.showwarning("Relatório", str(exc), parent=self.root)
            return
        totals, rows = self.db.monthly_movements(month, self.movement_kind_filter.get(), sale_number, self.movement_item_filter.get().strip())
        for row in self.movement_tree.get_children():
            self.movement_tree.delete(row)
        for movement in rows:
            move_date = datetime.strptime(movement["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
            self.movement_tree.insert("", "end", values=(move_date, movement["kind"], f"#{movement['sale_number']}" if movement["sale_number"] else "—", movement["barcode"], movement["description"], movement["quantity"], money(movement["unit_cost"]), movement["username"], movement["reference"]))
        self.movement_summary.configure(text=f"{displayed_month}   |   Entradas: {totals['incoming']} un. ({money(totals['incoming_value'])})   |   Saídas: {totals['outgoing']} un. ({money(totals['outgoing_value'])})   |   Movimentações: {len(rows)}")

    def refresh_all(self):
        self.refresh_products()
        self.refresh_stock_products()
        self.refresh_stock_history()
        self.refresh_cart()
        if hasattr(self, "daily_tree"):
            self.refresh_daily_report()
            self.refresh_month_report()
            self.refresh_movement_report()


def main():
    root = tk.Tk()
    ItelvinoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
