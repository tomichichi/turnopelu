import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "turnopelu.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cambiame-en-produccion")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL CHECK(role IN ('pro','client')),
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password TEXT NOT NULL,
  address TEXT NOT NULL DEFAULT '',
  city TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS slots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pro_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  time TEXT NOT NULL,
  service TEXT NOT NULL,
  price INTEGER NOT NULL,
  client_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  UNIQUE(pro_id, date, time)
);
"""


# ---------- base de datos ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(conn)
    conn.commit()
    conn.close()


def seed(conn):
    pw = generate_password_hash("demo")
    salons = [
        ("Barbería Don Carlos", "Av. Corrientes 1234", "Buenos Aires", "Corte clásico", 6000),
        ("Estilo Norte", "Av. Cabildo 2500", "Buenos Aires", "Corte + brushing", 9500),
        ("Peluquería Luna", "Bv. Oroño 800", "Rosario", "Corte mujer", 8000),
    ]
    for i, (name, addr, city, service, price) in enumerate(salons, 1):
        cur = conn.execute(
            "INSERT INTO users(role,name,email,password,address,city) VALUES('pro',?,?,?,?,?)",
            (name, f"pelu{i}@demo.com", pw, addr, city))
        for d in range(1, 4):
            for j, t in enumerate(["10:00", "12:30", "16:00", "18:00"]):
                if (d + j + i) % 3 == 0:
                    continue
                conn.execute(
                    "INSERT INTO slots(pro_id,date,time,service,price) VALUES(?,?,?,?,?)",
                    (cur.lastrowid, (date.today() + timedelta(days=d)).isoformat(), t,
                     service, price + j * 500))
    conn.execute(
        "INSERT INTO users(role,name,email,password) VALUES('client','Cliente Demo','cliente@demo.com',?)",
        (pw,))


# ---------- sesión, permisos, CSRF ----------
@app.before_request
def load_user():
    uid = session.get("uid")
    g.user = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if request.method == "POST":
        token = session.get("csrf")
        if not token or token != request.form.get("csrf"):
            abort(400, "Token CSRF inválido")


@app.context_processor
def inject():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"csrf": session["csrf"], "user": g.get("user"), "today": date.today().isoformat()}


def role_required(role):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                return redirect(url_for("login"))
            if g.user["role"] != role:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


@app.template_filter("fecha")
def fecha(s):
    dias = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    d = datetime.strptime(s, "%Y-%m-%d")
    return f"{dias[d.weekday()]} {d.day}/{d.month}"


@app.template_filter("peso")
def peso(n):
    return "$" + f"{n:,}".replace(",", ".")


# ---------- auth ----------
@app.route("/")
def index():
    if not g.user:
        return redirect(url_for("login"))
    return redirect(url_for("panel" if g.user["role"] == "pro" else "search"))


@app.route("/registro", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        role = f.get("role")
        name, email, pw = f.get("name", "").strip(), f.get("email", "").strip().lower(), f.get("password", "")
        addr, city = f.get("address", "").strip(), f.get("city", "").strip()
        if role not in ("pro", "client") or not name or not email or len(pw) < 6:
            flash("Completá todos los campos (contraseña de al menos 6 caracteres).")
        elif role == "pro" and (not addr or not city):
            flash("El peluquero tiene que indicar dirección y ciudad.")
        else:
            try:
                cur = db().execute(
                    "INSERT INTO users(role,name,email,password,address,city) VALUES(?,?,?,?,?,?)",
                    (role, name, email, generate_password_hash(pw), addr, city))
                db().commit()
            except sqlite3.IntegrityError:
                flash("Ese email ya está registrado.")
            else:
                session.clear()
                session["uid"] = cur.lastrowid
                return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if u and check_password_hash(u["password"], request.form.get("password", "")):
            session.clear()
            session["uid"] = u["id"]
            return redirect(url_for("index"))
        flash("Email o contraseña incorrectos.")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- peluquero ----------
@app.route("/panel")
@role_required("pro")
def panel():
    slots = db().execute(
        """SELECT s.*, c.name AS cname, c.email AS cemail FROM slots s
           LEFT JOIN users c ON c.id = s.client_id
           WHERE s.pro_id=? ORDER BY s.date, s.time""", (g.user["id"],)).fetchall()
    return render_template("panel.html", slots=slots)


@app.post("/panel/turnos")
@role_required("pro")
def add_slot():
    f = request.form
    try:
        start = datetime.strptime(f["date"], "%Y-%m-%d").date()
        datetime.strptime(f["time"], "%H:%M")
        price = int(f["price"])
        days = min(max(int(f.get("repeat") or 1), 1), 30)
        service = f["service"].strip()
        if price < 0 or not service:
            raise ValueError
    except (KeyError, ValueError):
        flash("Datos del turno inválidos.")
        return redirect(url_for("panel"))
    added = 0
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        try:
            db().execute("INSERT INTO slots(pro_id,date,time,service,price) VALUES(?,?,?,?,?)",
                         (g.user["id"], d, f["time"], service, price))
            added += 1
        except sqlite3.IntegrityError:
            pass  # ya existía ese horario
    db().commit()
    flash(f"{added} turno(s) agregado(s).")
    return redirect(url_for("panel"))


@app.post("/panel/turnos/<int:sid>/eliminar")
@role_required("pro")
def delete_slot(sid):
    db().execute("DELETE FROM slots WHERE id=? AND pro_id=?", (sid, g.user["id"]))
    db().commit()
    return redirect(url_for("panel"))


@app.route("/panel/local", methods=["GET", "POST"])
@role_required("pro")
def profile():
    if request.method == "POST":
        f = request.form
        if not all(f.get(k, "").strip() for k in ("name", "address", "city")):
            flash("Completá todos los campos.")
        else:
            db().execute("UPDATE users SET name=?,address=?,city=? WHERE id=?",
                         (f["name"].strip(), f["address"].strip(), f["city"].strip(), g.user["id"]))
            db().commit()
            flash("Datos guardados.")
            return redirect(url_for("profile"))
    return render_template("profile.html")


# ---------- cliente ----------
@app.route("/buscar")
@role_required("client")
def search():
    a = request.args
    now = datetime.now()
    sql = """SELECT s.*, u.name AS pname, u.address, u.city FROM slots s
             JOIN users u ON u.id = s.pro_id
             WHERE s.client_id IS NULL AND (s.date > ? OR (s.date = ? AND s.time >= ?))"""
    params = [now.strftime("%Y-%m-%d")] * 2 + [now.strftime("%H:%M")]
    if a.get("date"):
        sql += " AND s.date=?"; params.append(a["date"])
    if a.get("from"):
        sql += " AND s.time>=?"; params.append(a["from"])
    if a.get("to"):
        sql += " AND s.time<=?"; params.append(a["to"])
    if a.get("max", "").isdigit():
        sql += " AND s.price<=?"; params.append(int(a["max"]))
    if a.get("q", "").strip():
        sql += " AND (u.name || ' ' || u.address || ' ' || u.city) LIKE ?"
        params.append(f"%{a['q'].strip()}%")
    order = {"price": "s.price, s.date, s.time", "place": "u.city, u.name, s.date, s.time"}
    sql += " ORDER BY " + order.get(a.get("sort"), "s.date, s.time")
    return render_template("search.html", slots=db().execute(sql, params).fetchall(), f=a)


@app.post("/turnos/<int:sid>/reservar")
@role_required("client")
def book(sid):
    cur = db().execute("UPDATE slots SET client_id=? WHERE id=? AND client_id IS NULL",
                       (g.user["id"], sid))
    db().commit()
    flash("¡Turno reservado!" if cur.rowcount else "Ese turno ya no está disponible.")
    return redirect(url_for("mine" if cur.rowcount else "search"))


@app.route("/mis-reservas")
@role_required("client")
def mine():
    slots = db().execute(
        """SELECT s.*, u.name AS pname, u.address, u.city FROM slots s
           JOIN users u ON u.id = s.pro_id WHERE s.client_id=? ORDER BY s.date, s.time""",
        (g.user["id"],)).fetchall()
    return render_template("mine.html", slots=slots)


@app.post("/turnos/<int:sid>/cancelar")
@role_required("client")
def cancel(sid):
    db().execute("UPDATE slots SET client_id=NULL WHERE id=? AND client_id=?", (sid, g.user["id"]))
    db().commit()
    flash("Reserva cancelada.")
    return redirect(url_for("mine"))


init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
