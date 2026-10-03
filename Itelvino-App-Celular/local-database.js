/* Local-only data layer: all records stay in this browser's IndexedDB. */
(function () {
  "use strict";

  const DB_NAME = "itelvino-eletronicos-local";
  const DB_VERSION = 1;
  const SESSION_KEY = "itelvino-local-user";
  const STORES = ["products", "sales", "sale_items", "movements", "users"];
  let dbPromise;

  function openDB() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        const products = db.createObjectStore("products", { keyPath: "id", autoIncrement: true });
        products.createIndex("barcode", "barcode", { unique: true });
        products.createIndex("description", "description");
        db.createObjectStore("sales", { keyPath: "id", autoIncrement: true });
        const items = db.createObjectStore("sale_items", { keyPath: "id", autoIncrement: true });
        items.createIndex("sale_id", "sale_id");
        items.createIndex("product_id", "product_id");
        const movements = db.createObjectStore("movements", { keyPath: "id", autoIncrement: true });
        movements.createIndex("created_at", "created_at");
        movements.createIndex("sale_id", "sale_id");
        const users = db.createObjectStore("users", { keyPath: "usernameKey" });
        users.createIndex("username", "username", { unique: true });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("Não foi possível abrir os dados locais."));
      request.onblocked = () => reject(new Error("Feche outras abas do aplicativo e tente novamente."));
    });
    return dbPromise;
  }

  function transaction(storeNames, mode, setup) {
    return openDB().then(db => new Promise((resolve, reject) => {
      const tx = db.transaction(storeNames, mode);
      let result;
      let problem;
      tx.oncomplete = () => resolve(result);
      tx.onabort = () => reject(problem || tx.error || new Error("Não foi possível salvar os dados."));
      tx.onerror = () => { problem = tx.error || problem; };
      try { result = setup(tx, value => { result = value; }); }
      catch (error) { problem = error; try { tx.abort(); } catch (_) { reject(error); } }
    }));
  }

  function requestValue(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("Erro ao consultar o armazenamento local."));
    });
  }

  async function all(storeName) {
    const db = await openDB();
    return requestValue(db.transaction(storeName, "readonly").objectStore(storeName).getAll());
  }

  async function one(storeName, key) {
    const db = await openDB();
    return requestValue(db.transaction(storeName, "readonly").objectStore(storeName).get(key));
  }

  const stamp = () => {
    const d = new Date();
    const p = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  };
  const cents = value => Math.round((Number(value) + Number.EPSILON) * 100) / 100;
  const usernameKey = value => String(value || "").trim().toLocaleLowerCase("pt-BR");
  const normalize = value => String(value || "").trim().toLocaleLowerCase("pt-BR");
  const fail = message => { throw new Error(message); };

  async function passwordHash(password, salt) {
    if (!crypto.subtle) fail("Este navegador não permite proteger a senha. Abra o aplicativo pelo endereço HTTPS e instale-o.");
    const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
    const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", salt, iterations: 150000, hash: "SHA-256" }, key, 256);
    return Array.from(new Uint8Array(bits), b => b.toString(16).padStart(2, "0")).join("");
  }

  async function addUser(username, password) {
    const name = String(username || "").trim();
    if (!name || name.length > 80) fail("Informe um nome de usuário válido.");
    if (String(password || "").length < 6) fail("Use uma senha com pelo menos 6 caracteres.");
    const key = usernameKey(name);
    if (await one("users", key)) fail("Já existe um usuário com esse nome.");
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const saltHex = Array.from(salt, b => b.toString(16).padStart(2, "0")).join("");
    const record = { usernameKey: key, username: name, salt: saltHex, password_hash: await passwordHash(password, salt), created_at: stamp() };
    await transaction(["users"], "readwrite", tx => tx.objectStore("users").add(record));
    return name;
  }

  async function authenticate(username, password) {
    const record = await one("users", usernameKey(username));
    if (!record) return null;
    const salt = new Uint8Array((record.salt.match(/.{2}/g) || []).map(v => parseInt(v, 16)));
    const digest = await passwordHash(String(password || ""), salt);
    return digest === record.password_hash ? record.username : null;
  }

  function productData(product) {
    return Object.assign({}, product, { photo_url: product.photo_data || null });
  }

  async function readProducts(search = "") {
    const q = normalize(search);
    const products = await all("products");
    return products.filter(p => !q || normalize(`${p.barcode} ${p.description}`).includes(q))
      .sort((a, b) => a.description.localeCompare(b.description, "pt-BR", { sensitivity: "base" }))
      .map(productData);
  }

  async function saveProduct(data, username) {
    const barcode = String(data.barcode || "").trim();
    const description = String(data.description || "").trim();
    if (!barcode || !description) fail("Informe o código de barras e a descrição.");
    if (barcode.length > 80 || description.length > 240) fail("Código ou descrição muito longo.");
    const cost = Number(String(data.cost || "0").replace(",", "."));
    const price = Number(String(data.price || "0").replace(",", "."));
    const initialQty = Number(data.initial_qty || 0);
    if (!Number.isFinite(cost) || cost < 0 || !Number.isFinite(price) || price < 0) fail("Revise os valores de custo e venda.");
    if (!Number.isInteger(initialQty) || initialQty < 0) fail("Informe um estoque inicial válido.");
    const id = Number(data.id || 0);
    const existing = id ? await one("products", id) : null;
    if (id && !existing) fail("Produto não encontrado.");
    const duplicates = await readProducts();
    if (duplicates.some(p => p.id !== id && p.barcode === barcode)) fail("Esse código de barras já está cadastrado.");
    let photo = existing ? existing.photo_data || null : null;
    if (data.remove_photo) photo = null;
    if (data.photo_data) {
      if (!String(data.photo_data).startsWith("data:image/jpeg;base64,") && !String(data.photo_data).startsWith("data:image/png;base64,")) fail("Envie uma foto JPEG ou PNG.");
      if (String(data.photo_data).length > 7 * 1024 * 1024) fail("A foto deve ter no máximo 5 MB.");
      photo = data.photo_data;
    }
    const created = stamp();
    return transaction(initialQty > 0 && !existing ? ["products", "movements"] : ["products"], "readwrite", (tx, setResult) => {
      const store = tx.objectStore("products");
      const product = { barcode, description, cost: cents(cost), price: cents(price), photo_data: photo, quantity: existing ? existing.quantity : 0, created_at: existing ? existing.created_at : created };
      if (existing) {
        product.id = id;
        store.put(product);
        setResult(id);
      } else {
        const request = store.add(product);
        if (initialQty > 0) request.onsuccess = () => {
          const newId = request.result;
          store.put(Object.assign({}, product, { id: newId, quantity: initialQty }));
          tx.objectStore("movements").add({ product_id: newId, kind: "Entrada inicial", quantity: initialQty, unit_cost: cents(cost), note: "Saldo inicial do cadastro", sale_id: null, username, created_at: created });
          setResult(newId);
        };
        else request.onsuccess = () => setResult(request.result);
      }
    });
  }

  async function saveMovement(data, username) {
    const productId = Number(data.product_id), qty = Number(data.quantity), kind = String(data.kind || "");
    if (!Number.isInteger(productId) || productId < 1) fail("Produto não encontrado.");
    if (!Number.isInteger(qty) || qty < 1) fail("Informe uma quantidade inteira válida.");
    if (!["Entrada", "Saída"].includes(kind)) fail("Escolha entrada ou saída.");
    const costText = String(data.unit_cost || "").trim();
    const suppliedCost = costText ? Number(costText.replace(",", ".")) : null;
    if (suppliedCost != null && (!Number.isFinite(suppliedCost) || suppliedCost < 0)) fail("Informe o custo unitário corretamente.");
    const created = stamp();
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(["products", "movements"], "readwrite");
      let problem, result = { ok: true };
      tx.oncomplete = () => resolve(result);
      tx.onabort = () => reject(problem || tx.error || new Error("Não foi possível registrar a movimentação."));
      const request = tx.objectStore("products").get(productId);
      request.onsuccess = () => {
        const product = request.result;
        if (!product) { problem = new Error("Produto não encontrado."); tx.abort(); return; }
        if (kind === "Saída" && product.quantity < qty) { problem = new Error("A saída é maior que o saldo atual do produto."); tx.abort(); return; }
        const unitCost = suppliedCost == null ? Number(product.cost) : suppliedCost;
        const next = Object.assign({}, product, { quantity: product.quantity + (kind === "Entrada" ? qty : -qty), cost: kind === "Entrada" ? cents(unitCost) : product.cost });
        tx.objectStore("products").put(next);
        tx.objectStore("movements").add({ product_id: productId, kind: kind === "Saída" ? "Saída manual" : kind, quantity: qty, unit_cost: cents(unitCost), note: String(data.note || "").trim().slice(0, 240), sale_id: null, username, created_at: created });
      };
    });
  }

  async function saveSale(data, username) {
    if (!Array.isArray(data.items) || !data.items.length) fail("Adicione pelo menos um produto à venda.");
    const quantities = new Map();
    for (const line of data.items) {
      const id = Number(line.product_id), qty = Number(line.quantity);
      if (!Number.isInteger(id) || id < 1 || !Number.isInteger(qty) || qty < 1) fail("Revise os produtos e quantidades da venda.");
      quantities.set(id, (quantities.get(id) || 0) + qty);
    }
    const discount = Number(String(data.discount_percent || "0").replace(",", "."));
    if (!Number.isFinite(discount) || discount < 0 || discount > 100) fail("O desconto deve ficar entre 0% e 100%.");
    const payment = String(data.payment_method || "");
    if (!["Dinheiro", "PIX", "Cartão de débito", "Cartão de crédito", "Outro"].includes(payment)) fail("Escolha uma forma de pagamento válida.");
    const installments = Number(data.installments || 1);
    if (!Number.isInteger(installments) || installments < 1 || installments > 48) fail("O número de parcelas deve ficar entre 1 e 48.");
    const created = stamp();
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(["products", "sales", "sale_items", "movements"], "readwrite");
      let problem, result;
      const cart = [];
      let pending = quantities.size;
      tx.oncomplete = () => resolve(result);
      tx.onabort = () => reject(problem || tx.error || new Error("Não foi possível concluir a venda."));
      const productStore = tx.objectStore("products");
      for (const [id, quantity] of quantities) {
        const request = productStore.get(id);
        request.onsuccess = () => {
          const product = request.result;
          if (!product) { problem = new Error("Um dos produtos não foi encontrado."); tx.abort(); return; }
          if (product.quantity < quantity) { problem = new Error(`Estoque insuficiente para ${product.description}.`); tx.abort(); return; }
          cart.push({ product, quantity });
          pending--;
          if (pending) return;
          const subtotal = cents(cart.reduce((sum, item) => sum + item.product.price * item.quantity, 0));
          const discountValue = cents(subtotal * discount / 100), total = cents(subtotal - discountValue);
          const saleRequest = tx.objectStore("sales").add({ subtotal, discount_percent: discount, discount_value: discountValue, total, payment_method: payment, installments, username, created_at: created });
          saleRequest.onsuccess = () => {
            const saleId = saleRequest.result, itemStore = tx.objectStore("sale_items"), movementStore = tx.objectStore("movements");
            for (const { product, quantity } of cart) {
              itemStore.add({ sale_id: saleId, product_id: product.id, barcode: product.barcode, description: product.description, quantity, unit_price: product.price, unit_cost: product.cost, line_total: cents(quantity * product.price) });
              productStore.put(Object.assign({}, product, { quantity: product.quantity - quantity }));
              movementStore.add({ product_id: product.id, kind: "Venda", quantity, unit_cost: product.cost, note: `Venda #${saleId}`, sale_id: saleId, username, created_at: created });
            }
            result = { sale_id: saleId, subtotal, discount: discountValue, total };
          };
        };
      }
    });
  }

  function containsItem(items, query) {
    const q = normalize(query);
    return !q || items.some(i => normalize(`${i.barcode} ${i.description}`).includes(q));
  }

  async function saleRows(dayOrMonth, isMonth, saleFilter, itemQuery) {
    const [sales, saleItems] = await Promise.all([all("sales"), all("sale_items")]);
    const bySale = new Map();
    for (const item of saleItems) {
      if (!bySale.has(item.sale_id)) bySale.set(item.sale_id, []);
      bySale.get(item.sale_id).push(item);
    }
    return sales.filter(s => (isMonth ? s.created_at.slice(0, 7) : s.created_at.slice(0, 10)) === dayOrMonth)
      .filter(s => !saleFilter || s.id === Number(saleFilter))
      .filter(s => containsItem(bySale.get(s.id) || [], itemQuery))
      .map(s => Object.assign({}, s, { item_list: (bySale.get(s.id) || []).map(i => `${i.description} (x${i.quantity})`).join(", ") }))
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
  }

  async function reportData(query) {
    const day = query.get("day") || stamp().slice(0, 10), month = query.get("month") || day.slice(0, 7);
    const saleFilter = String(query.get("sale") || "").replace(/^#/, ""), itemQuery = query.get("item") || "";
    const [dailySales, monthlySales, saleItems] = await Promise.all([
      saleRows(day, false, saleFilter, itemQuery), saleRows(month, true, saleFilter, itemQuery), all("sale_items")
    ]);
    const summarize = rows => ({ sale_count: rows.length, count: rows.length, subtotal: cents(rows.reduce((s, x) => s + x.subtotal, 0)), discount: cents(rows.reduce((s, x) => s + x.discount_value, 0)), total: cents(rows.reduce((s, x) => s + x.total, 0)) });
    const sumItems = rows => {
      const ids = new Set(rows.map(s => s.id));
      const selected = saleItems.filter(i => ids.has(i.sale_id));
      return { quantity: selected.reduce((s, i) => s + i.quantity, 0), invested: cents(selected.reduce((s, i) => s + i.quantity * Number(i.unit_cost || 0), 0)), unknown_cost_quantity: selected.filter(i => i.unit_cost == null).reduce((s, i) => s + i.quantity, 0) };
    };
    const payments = rows => {
      const groups = new Map();
      rows.forEach(s => { const g = groups.get(s.payment_method) || { payment_method: s.payment_method, amount: 0, count: 0, total: 0 }; g.amount++; g.count++; g.total = cents(g.total + s.total); groups.set(s.payment_method, g); });
      return Array.from(groups.values());
    };
    const dailySummary = summarize(dailySales), monthlySummary = summarize(monthlySales);
    return {
      day, month,
      daily: { summary: dailySummary, items: sumItems(dailySales), payments: payments(dailySales), sales: dailySales },
      monthly: { summary: monthlySummary, items: sumItems(monthlySales), methods: payments(monthlySales), sales: monthlySales }
    };
  }

  async function movementRows(query) {
    const month = query.get("month") || stamp().slice(0, 7), kind = query.get("kind") || "Todos";
    const saleFilter = String(query.get("sale") || "").replace(/^#/, ""), itemQuery = query.get("item") || "";
    const [movements, products, sales] = await Promise.all([all("movements"), all("products"), all("sales")]);
    const productMap = new Map(products.map(p => [p.id, p])), saleMap = new Map(sales.map(s => [s.id, s]));
    const rows = movements.filter(m => m.created_at.slice(0, 7) === month)
      .filter(m => kind === "Todos" || (kind === "Entradas" ? ["Entrada", "Entrada inicial"].includes(m.kind) : ["Saída manual", "Venda"].includes(m.kind)))
      .filter(m => !saleFilter || Number(m.sale_id) === Number(saleFilter))
      .filter(m => { const p = productMap.get(m.product_id); return p && (!itemQuery || normalize(`${p.barcode} ${p.description}`).includes(normalize(itemQuery))); })
      .map(m => {
        const p = productMap.get(m.product_id), sale = m.sale_id ? saleMap.get(m.sale_id) : null;
        return Object.assign({}, m, { barcode: p.barcode, description: p.description, payment_method: sale?.payment_method || null, installments: sale?.installments || null, sale_number: sale?.id || null, reference: sale ? `Venda #${sale.id} · ${sale.payment_method} · ${sale.installments} parcela(s)` : m.note });
      })
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
    const incoming = rows.filter(r => ["Entrada", "Entrada inicial"].includes(r.kind)), outgoing = rows.filter(r => ["Saída manual", "Venda"].includes(r.kind));
    return { totals: { incoming: incoming.reduce((s, r) => s + r.quantity, 0), outgoing: outgoing.reduce((s, r) => s + r.quantity, 0), incoming_value: cents(incoming.reduce((s, r) => s + r.quantity * r.unit_cost, 0)), outgoing_value: cents(outgoing.reduce((s, r) => s + r.quantity * r.unit_cost, 0)) }, rows };
  }

  async function exportBackup() {
    const data = { app: "itelvino-eletronicos-local", version: 1, exported_at: stamp(), products: await all("products"), sales: await all("sales"), sale_items: await all("sale_items"), movements: await all("movements"), users: await all("users") };
    return new Blob([JSON.stringify(data)], { type: "application/json" });
  }

  async function restoreBackup(text) {
    if (String(text).length > 100 * 1024 * 1024) fail("O arquivo de backup ultrapassa 100 MB.");
    let data;
    try { data = JSON.parse(text); } catch (_) { fail("O arquivo escolhido não é um backup JSON válido."); }
    if (!data || data.app !== "itelvino-eletronicos-local" || data.version !== 1 || STORES.some(name => !Array.isArray(data[name]))) fail("Esse arquivo não é um backup compatível do Itelvino para celular.");
    if (!data.users.length || !data.products.every(p => p && Number.isInteger(p.id) && typeof p.barcode === "string" && typeof p.description === "string")) fail("O backup está incompleto ou inválido.");
    await transaction(STORES, "readwrite", tx => {
      for (const name of STORES) {
        const store = tx.objectStore(name);
        store.clear();
        for (const row of data[name]) store.put(row);
      }
    });
    localStorage.removeItem(SESSION_KEY);
    return { ok: true };
  }

  async function localApi(path, options = {}) {
    const url = new URL(path, location.href), method = String(options.method || "GET").toUpperCase();
    let body = {};
    if (options.body && typeof options.body === "string") {
      try { body = JSON.parse(options.body); } catch (_) { return response({ error: "Os dados enviados não são válidos." }, 400); }
    } else if (options.body && typeof options.body === "object") body = options.body;
    const ok = data => response(data, 200), error = (message, status = 400) => response({ error: message }, status);
    try {
      if (url.pathname === "/api/status" || url.pathname.endsWith("/api/status")) return ok({ setup_needed: (await all("users")).length === 0 });
      if (url.pathname.endsWith("/api/setup") && method === "POST") {
        if ((await all("users")).length) return error("A configuração inicial já foi concluída.", 409);
        const username = await addUser(body.username, body.password);
        localStorage.setItem(SESSION_KEY, username);
        return ok({ username });
      }
      if (url.pathname.endsWith("/api/login") && method === "POST") {
        const username = await authenticate(body.username, body.password);
        if (!username) return error("Usuário ou senha incorretos.", 401);
        localStorage.setItem(SESSION_KEY, username);
        return ok({ username });
      }
      if (url.pathname.endsWith("/api/logout") && method === "POST") { localStorage.removeItem(SESSION_KEY); return ok({ ok: true }); }
      const current = localStorage.getItem(SESSION_KEY);
      if (!current || !(await one("users", usernameKey(current)))) return error("Entre com seu usuário e senha para continuar.", 401);
      if (url.pathname.endsWith("/api/me")) return ok({ username: current });
      if (url.pathname.endsWith("/api/products") && method === "GET") return ok({ products: await readProducts(url.searchParams.get("q") || "") });
      if (url.pathname.endsWith("/api/products") && method === "POST") return ok({ ok: true, id: await saveProduct(body, current) });
      if (url.pathname.endsWith("/api/stock") && method === "POST") return ok(await saveMovement(body, current));
      if (url.pathname.endsWith("/api/sales") && method === "POST") return ok(await saveSale(body, current));
      if (url.pathname.endsWith("/api/reports")) return ok(await reportData(url.searchParams));
      if (url.pathname.endsWith("/api/movements")) return ok(await movementRows(url.searchParams));
      if (url.pathname.endsWith("/api/users") && method === "POST") { await addUser(body.username, body.password); return ok({ ok: true }); }
      if (url.pathname.endsWith("/api/password") && method === "POST") {
        if (!await authenticate(current, body.current_password)) return error("Usuário ou senha atual incorretos.");
        if (String(body.new_password || "").length < 6) return error("Use uma nova senha com pelo menos 6 caracteres.");
        const salt = crypto.getRandomValues(new Uint8Array(16)), saltHex = Array.from(salt, b => b.toString(16).padStart(2, "0")).join("");
        const record = await one("users", usernameKey(current));
        record.salt = saltHex; record.password_hash = await passwordHash(body.new_password, salt);
        await transaction(["users"], "readwrite", tx => tx.objectStore("users").put(record));
        return ok({ ok: true });
      }
      if (url.pathname.endsWith("/api/backup")) return blobResponse(await exportBackup());
      if (url.pathname.endsWith("/api/restore") && method === "POST") return ok(await restoreBackup(body.file_text || ""));
      return error("Endereço não encontrado.", 404);
    } catch (err) {
      return error(err?.message || "Ocorreu um erro ao salvar os dados." , 400);
    }
  }

  function response(data, status) {
    return { ok: status < 400, status, json: async () => data, blob: async () => new Blob([JSON.stringify(data)], { type: "application/json" }) };
  }
  function blobResponse(blob) { return { ok: true, status: 200, json: async () => ({}), blob: async () => blob }; }

  window.itelvinoLocalApi = localApi;
})();
