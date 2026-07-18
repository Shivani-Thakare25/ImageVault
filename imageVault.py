import tkinter as tk
from tkinter import filedialog, messagebox
import json
import hmac
import secrets
import time
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PIL import Image, ImageTk, ImageDraw, ImageFilter
import cv2
import numpy as np
import mysql.connector
from mysql.connector import Error


# ─────────────────────────────────────────────────────────
#  MYSQL CONFIGURATION
# ─────────────────────────────────────────────────────────

DB_CONFIG = {
    "host":     "localhost",
    "port":     3306,
    "user":     "root",
    "password": "*********",
    "database": "imagevault"
}

# ─────────────────────────────────────────────────────────
#  SMTP CONFIGURATION
# ─────────────────────────────────────────────────────────

SMTP_CONFIG = {
    "server":   "smtp.gmail.com",
    "port":     587,
    "sender":   "senders_email",
    "password": "*******",
}

# ─────────────────────────────────────────────────────────
#  DATABASE INIT
# ─────────────────────────────────────────────────────────


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def init_db():
    cfg = {k: v for k, v in DB_CONFIG.items() if k != "database"}
    try:
        conn = mysql.connector.connect(**cfg)
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_CONFIG['database']}`")
        conn.commit()
        cur.close()
        conn.close()
    except Error as e:
        messagebox.showerror(
            "Database Error",
            f"Could not connect to MySQL.\n\nError: {e}"
        )
        raise SystemExit(1)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            username     VARCHAR(64)  NOT NULL UNIQUE,
            email        VARCHAR(128) NOT NULL,
            image_hash   VARCHAR(64)  NOT NULL,
            image_width  INT          NOT NULL,
            image_height INT          NOT NULL,
            clicks       TEXT         NOT NULL,
            created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Folders table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            user_id    INT          NOT NULL,
            name       VARCHAR(128) NOT NULL,
            icon       VARCHAR(16)  DEFAULT '📁',
            color      VARCHAR(16)  DEFAULT '#b30000',
            created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Passwords table (with optional folder)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS passwords (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            user_id    INT          NOT NULL,
            folder_id  INT          DEFAULT NULL,
            site       VARCHAR(128) NOT NULL,
            username   VARCHAR(128) DEFAULT '',
            password   VARCHAR(512) NOT NULL,
            added_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id)   REFERENCES users(id)   ON DELETE CASCADE,
            FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
        )
    """)

    # Notes table (with optional folder)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            user_id    INT          NOT NULL,
            folder_id  INT          DEFAULT NULL,
            title      VARCHAR(256) NOT NULL,
            content    TEXT         NOT NULL,
            added_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id)   REFERENCES users(id)   ON DELETE CASCADE,
            FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
        )
    """)

    # Secret texts table (with optional folder)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS secret_texts (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            user_id    INT          NOT NULL,
            folder_id  INT          DEFAULT NULL,
            label      VARCHAR(256) NOT NULL,
            content    TEXT         NOT NULL,
            added_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id)   REFERENCES users(id)   ON DELETE CASCADE,
            FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


# ─────────────────────────────────────────────────────────
#  USER QUERIES
# ─────────────────────────────────────────────────────────

def db_get_user(username):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE username = %s", (username.lower(),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def db_user_exists(username):
    return db_get_user(username) is not None


def db_get_user_by_email(email):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def db_create_user(username, email, image_hash, image_w, image_h, clicks):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, email, image_hash, image_width, image_height, clicks) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (username.lower(), email, image_hash, image_w, image_h, json.dumps(clicks))
    )
    conn.commit()
    cur.close()
    conn.close()


# ─────────────────────────────────────────────────────────
#  FOLDER QUERIES
# ─────────────────────────────────────────────────────────

def db_get_folders(user_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT * FROM folders WHERE user_id = %s ORDER BY name ASC", (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_create_folder(user_id, name, icon="📁", color="#b30000"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO folders (user_id, name, icon, color) VALUES (%s, %s, %s, %s)",
        (user_id, name, icon, color)
    )
    conn.commit()
    new_id = cur.lastrowid
    cur.close()
    conn.close()
    return new_id


def db_rename_folder(folder_id, new_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE folders SET name = %s WHERE id = %s",
                (new_name, folder_id))
    conn.commit()
    cur.close()
    conn.close()


def db_delete_folder(folder_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM folders WHERE id = %s", (folder_id,))
    conn.commit()
    cur.close()
    conn.close()


def db_folder_item_counts(folder_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM passwords WHERE folder_id = %s", (folder_id,))
    pw = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM notes WHERE folder_id = %s", (folder_id,))
    nt = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM secret_texts WHERE folder_id = %s", (folder_id,))
    st = cur.fetchone()[0]
    cur.close()
    conn.close()
    return pw, nt, st


# ─────────────────────────────────────────────────────────
#  PASSWORD QUERIES
# ─────────────────────────────────────────────────────────

def db_get_passwords(user_id, folder_id=None):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    if folder_id is None:
        cur.execute(
            "SELECT * FROM passwords WHERE user_id = %s ORDER BY added_at DESC",
            (user_id,)
        )
    else:
        cur.execute(
            "SELECT * FROM passwords WHERE user_id = %s AND folder_id = %s ORDER BY added_at DESC",
            (user_id, folder_id)
        )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_add_password(user_id, site, username, password, folder_id=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO passwords (user_id, folder_id, site, username, password) VALUES (%s,%s,%s,%s,%s)",
        (user_id, folder_id, site, username, password)
    )
    conn.commit()
    cur.close()
    conn.close()


def db_delete_password(pw_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM passwords WHERE id = %s", (pw_id,))
    conn.commit()
    cur.close()
    conn.close()


def db_move_password(pw_id, folder_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE passwords SET folder_id = %s WHERE id = %s",
                (folder_id, pw_id))
    conn.commit()
    cur.close()
    conn.close()


# ─────────────────────────────────────────────────────────
#  NOTE QUERIES
# ─────────────────────────────────────────────────────────

def db_get_notes(user_id, folder_id=None):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    if folder_id is None:
        cur.execute(
            "SELECT * FROM notes WHERE user_id = %s ORDER BY added_at DESC",
            (user_id,)
        )
    else:
        cur.execute(
            "SELECT * FROM notes WHERE user_id = %s AND folder_id = %s ORDER BY added_at DESC",
            (user_id, folder_id)
        )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_add_note(user_id, title, content, folder_id=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO notes (user_id, folder_id, title, content) VALUES (%s,%s,%s,%s)",
        (user_id, folder_id, title, content)
    )
    conn.commit()
    cur.close()
    conn.close()


def db_delete_note(note_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM notes WHERE id = %s", (note_id,))
    conn.commit()
    cur.close()
    conn.close()


def db_move_note(note_id, folder_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE notes SET folder_id = %s WHERE id = %s",
                (folder_id, note_id))
    conn.commit()
    cur.close()
    conn.close()


# ─────────────────────────────────────────────────────────
#  SECRET TEXT QUERIES
# ─────────────────────────────────────────────────────────

def db_get_secret_texts(user_id, folder_id=None):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    if folder_id is None:
        cur.execute(
            "SELECT * FROM secret_texts WHERE user_id = %s ORDER BY added_at DESC",
            (user_id,)
        )
    else:
        cur.execute(
            "SELECT * FROM secret_texts WHERE user_id = %s AND folder_id = %s ORDER BY added_at DESC",
            (user_id, folder_id)
        )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_add_secret_text(user_id, label, content, folder_id=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO secret_texts (user_id, folder_id, label, content) VALUES (%s,%s,%s,%s)",
        (user_id, folder_id, label, content)
    )
    conn.commit()
    cur.close()
    conn.close()


def db_delete_secret_text(st_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM secret_texts WHERE id = %s", (st_id,))
    conn.commit()
    cur.close()
    conn.close()


def db_move_secret_text(st_id, folder_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE secret_texts SET folder_id = %s WHERE id = %s", (folder_id, st_id))
    conn.commit()
    cur.close()
    conn.close()

# ─────────────────────────────────────────────────────────
#  IMAGE HASHING (pHash)
# ─────────────────────────────────────────────────────────


def compute_phash(pil_image):
    gray = pil_image.convert("L").resize((32, 32))
    arr = np.array(gray, dtype=np.float32)
    dct = cv2.dct(arr)
    dct_low = dct[:8, :8].flatten()
    median = np.median(dct_low)
    bits = (dct_low > median).astype(int)
    return "".join(map(str, bits))


def images_match(stored, new, threshold=10):
    return sum(a != b for a, b in zip(stored, new)) <= threshold


# ─────────────────────────────────────────────────────────
#  CLICK PATTERN
# ─────────────────────────────────────────────────────────

def normalize_point(x, y, img_w, img_h):
    return round(x / img_w * 1000), round(y / img_h * 1000)


def clicks_match(stored, attempt, tolerance=60):
    if len(stored) != len(attempt):
        return False
    for (sx, sy), (ax, ay) in zip(stored, attempt):
        if abs(sx - ax) > tolerance or abs(sy - ay) > tolerance:
            return False
    return True


# ─────────────────────────────────────────────────────────
#  OTP
# ─────────────────────────────────────────────────────────

def generate_otp():
    code = str(secrets.randbelow(900000) + 100000)
    expiry = time.time() + 300
    return code, expiry


def send_otp_email(to_email, otp_code):
    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "ImageVault - Your One-Time Password"
            msg["From"] = SMTP_CONFIG["sender"]
            msg["To"] = to_email
            html = f"""\
            <html><body style="font-family:Arial,sans-serif;background:#0a0e14;color:#e2e8f0;padding:30px">
              <div style="max-width:420px;margin:auto;background:#111820;border-radius:12px;padding:30px;text-align:center">
                <h2 style="color:#00c8f0;margin-bottom:4px">&#128274; ImageVault</h2>
                <p style="color:#4a6680;font-size:13px">Your one-time password</p>
                <div style="font-size:36px;letter-spacing:12px;font-weight:bold;color:#00c8f0;
                            background:#1a2535;border-radius:8px;padding:16px;margin:20px 0">
                  {otp_code}
                </div>
                <p style="color:#4a6680;font-size:12px">This code expires in <b>5 minutes</b>.</p>
              </div>
            </body></html>"""
            msg.attach(MIMEText(
                f"Your ImageVault OTP is: {otp_code}\nExpires in 5 minutes.", "plain"))
            msg.attach(MIMEText(html, "html"))
            with smtplib.SMTP(SMTP_CONFIG["server"], SMTP_CONFIG["port"]) as server:
                server.starttls()
                server.login(SMTP_CONFIG["sender"], SMTP_CONFIG["password"])
                server.sendmail(SMTP_CONFIG["sender"],
                                to_email, msg.as_string())
            print(f"OTP email sent to {to_email}")
        except Exception as e:
            print(f"Failed to send OTP email: {e}")
    threading.Thread(target=_send, daemon=True).start()


# ─────────────────────────────────────────────────────────
#  THEME
# ─────────────────────────────────────────────────────────

BG = "#f5ecd7"
SURFACE = "#bdaf8e"
SURFACE2 = "#e6d8b5"
BORDER = "#2b2b2b"
ACCENT = "#b30000"
ACCENT2 = "#000000"
SUCCESS = "#1a7f37"
DANGER = "#b30000"
WARNING = "#cc5500"
TEXT = "#111111"
MUTED = "#5a5a5a"
FONT_MONO = ("Courier New", 11)

FOLDER_COLORS = ["#b30000", "#1a5276",
                 "#1a7f37", "#7d3c98", "#cc5500", "#2b2b2b"]
FOLDER_ICONS = ["📁", "🔐", "📝", "🗂️", "💼", "🔒", "⭐", "🏦"]


def style_btn(btn, color=ACCENT, fg="#ffffff"):
    btn.configure(
        bg=color, fg=fg, relief="solid", bd=1, cursor="hand2",
        font=("Courier New", 11, "bold"), padx=12, pady=6,
        activebackground="#000000", activeforeground="#ffffff"
    )


def style_entry(entry):
    entry.configure(
        bg=SURFACE2, fg=TEXT, insertbackground="black",
        relief="solid", bd=1, font=FONT_MONO
    )


def style_small_btn(btn, color=SURFACE2, fg=TEXT):
    btn.configure(
        bg=color, fg=fg, relief="flat", cursor="hand2",
        font=("Courier New", 9, "bold"), padx=6, pady=3
    )


# ─────────────────────────────────────────────────────────
#  IMAGE CLICK CANVAS
# ─────────────────────────────────────────────────────────

class ImageClickCanvas(tk.Frame):
    MAX_CLICKS = 5
    DOT_RADIUS = 12

    def __init__(self, parent, max_w=500, max_h=350, stealth_mode=False, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.max_w = max_w
        self.max_h = max_h
        self.stealth_mode = stealth_mode
        self.clicks = []
        self._canvas_clicks = []
        self.pil_image = None
        self.scale = 1.0
        self._reveal = False
        self._blurred_img = None

        self.canvas = tk.Canvas(self, bg=SURFACE2, cursor="crosshair",
                                highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_click)

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", pady=0.5)
        self._hint = tk.Label(bottom, text="No image loaded",
                              bg=BG, fg=MUTED, font=FONT_MONO)
        self._hint.pack(side="left")

        if self.stealth_mode:
            rb = tk.Button(bottom, text="Hold to Reveal",
                           bg=SURFACE2, fg=WARNING, relief="flat", cursor="hand2",
                           font=("Courier New", 9, "bold"), padx=10, pady=4,
                           activebackground=SURFACE2, activeforeground=TEXT)
            rb.pack(side="right", padx=(8, 0))
            rb.bind("<ButtonPress-1>", lambda e: self._set_reveal(True))
            rb.bind("<ButtonRelease-1>", lambda e: self._set_reveal(False))

        self._tk_img = None

    def load_image(self, pil_image):
        self.pil_image = pil_image
        self.clicks = []
        self._canvas_clicks = []
        self._blurred_img = None
        self._fit_and_draw()

    def reset(self):
        self.clicks = []
        self._canvas_clicks = []
        self.pil_image = None
        self._blurred_img = None
        self._tk_img = None
        self.canvas.delete("all")
        self._hint.config(text="No image loaded", fg=MUTED)

    def get_clicks(self):
        return list(self.clicks)

    def _set_reveal(self, val):
        self._reveal = val
        self._redraw()

    def _fit_and_draw(self):
        if not self.pil_image:
            return
        w, h = self.pil_image.size
        scale = min(self.max_w / w, self.max_h / h, 1.0)
        self.scale = scale
        dw, dh = int(w * scale), int(h * scale)
        self.canvas.config(width=dw, height=dh)
        resized = self.pil_image.resize((dw, dh), Image.LANCZOS)
        self._base_img = resized.copy()
        if self.stealth_mode:
            blurred = resized.filter(ImageFilter.GaussianBlur(radius=14))
            dark = Image.new("RGB", resized.size, (0, 8, 20))
            self._blurred_img = Image.blend(blurred, dark, alpha=0.45)
        self._redraw()

    def _redraw(self):
        if not self.pil_image:
            return
        n = len(self.clicks)
        if self.stealth_mode and not self._reveal:
            base = self._blurred_img.copy() if self._blurred_img else self._base_img.copy()
            self._tk_img = ImageTk.PhotoImage(base)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)
            self._hint.config(text=f"  Stealth  |  {n}/{self.MAX_CLICKS} clicks recorded",
                              fg=SUCCESS if n >= 3 else WARNING)
        else:
            img = self._base_img.copy()
            draw = ImageDraw.Draw(img)
            for cx, cy in self._canvas_clicks:
                r = self.DOT_RADIUS
                draw.ellipse([cx-r, cy-r, cx+r, cy+r],
                             fill=(0, 200, 240, 180), outline=(0, 200, 240), width=2)
            self._tk_img = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)
            label = (f"  Revealed  |  {n}/{self.MAX_CLICKS} clicks  |  Release to hide"
                     if (self.stealth_mode and self._reveal)
                     else f"  {n}/{self.MAX_CLICKS} points  |  Click on image to add")
            self._hint.config(text=label, fg=ACCENT if n >= 3 else MUTED)

    def _on_click(self, event):
        if len(self.clicks) >= self.MAX_CLICKS or not self.pil_image:
            return
        cx, cy = event.x, event.y
        self.clicks.append((round(cx / self.scale), round(cy / self.scale)))
        self._canvas_clicks.append((cx, cy))
        self._redraw()


# ─────────────────────────────────────────────────────────
#  BASE SCREEN
# ─────────────────────────────────────────────────────────

class Screen(tk.Frame):
    def __init__(self, master, app, **kw):
        super().__init__(master, bg=BG, **kw)
        self.app = app

    def on_show(self):
        pass


# ─────────────────────────────────────────────────────────
#  WELCOME SCREEN
# ─────────────────────────────────────────────────────────

class WelcomeScreen(Screen):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._build()

    def _build(self):
        tk.Label(self, text="⚠ CLASSIFIED FILE ⚠", bg=BG, fg=ACCENT,
                 font=("Courier New", 12, "bold")).pack(pady=5)
        tk.Label(self, text="SECURE", bg=BG, font=(
            "Segoe UI", 48)).pack(pady=(60, 10))
        tk.Label(self, text="TOP SECRET", bg=BG, fg=ACCENT,
                 font=("Courier New", 28, "bold")).pack()
        tk.Label(self, text="FEDERAL IMAGE VAULT SYSTEM", bg=BG, fg=TEXT,
                 font=("Courier New", 14)).pack(pady=(0, 10))
        tk.Label(self, text="Your image IS your password", bg=BG, fg=MUTED,
                 font=("Segoe UI", 11)).pack(pady=(4, 40))

        badges = tk.Frame(self, bg=BG)
        badges.pack(pady=(0, 40))
        for icon, label in [("IMAGE KEY", "Secret Image"), ("ACCESS POINT", "Click Pattern"),
                            ("VERIFY", "OTP Verify"), ("FOLDERS", "Organized Vault")]:
            f = tk.Frame(badges, bg=SURFACE, padx=18, pady=12)
            f.pack(side="left", padx=8)
            tk.Label(f, text=icon, bg=SURFACE, font=("Segoe UI", 16)).pack()
            tk.Label(f, text=label, bg=SURFACE, fg=MUTED,
                     font=("Segoe UI", 9, "bold")).pack(pady=(4, 0))

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack()
        reg_btn = tk.Button(btn_frame, text="Create Account",
                            command=lambda: self.app.show("register"))
        style_btn(reg_btn)
        reg_btn.pack(side="left", padx=8)
        login_btn = tk.Button(btn_frame, text="Sign In",
                              command=lambda: self.app.show("login"))
        style_btn(login_btn, color=SURFACE2, fg=TEXT)
        login_btn.pack(side="left", padx=8)


# ─────────────────────────────────────────────────────────
#  REGISTER SCREEN
# ─────────────────────────────────────────────────────────

class RegisterScreen(Screen):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.pil_image = None
        self._reg_otp = None
        self._reg_otp_expiry = 0
        self._email_verified = False
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=30, pady=(20, 0))
        tk.Button(hdr, text="<- Back", command=lambda: self.app.show("welcome"),
                  bg=BG, fg=MUTED, relief="flat", cursor="hand2",
                  font=("Segoe UI", 10)).pack(side="left")
        tk.Label(hdr, text="Create Account", bg=BG, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=16)

        step_bar = tk.Frame(self, bg=BG)
        step_bar.pack(fill="x", padx=30, pady=(10, 0))
        for _ in range(3):
            f = tk.Frame(step_bar, bg=BORDER, height=3)
            f.pack(side="left", expand=True, fill="x", padx=2)
        self._step_bars = step_bar.winfo_children()

        self.pages = {}
        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True, padx=30, pady=10)
        self.pages[1] = self._page1(container)
        self.pages[2] = self._page2(container)
        self.pages[3] = self._page3(container)
        self._show_page(1)

    def _show_page(self, n):
        for k, f in self.pages.items():
            f.pack_forget()
        self.pages[n].pack(fill="both", expand=True)
        for i, bar in enumerate(self._step_bars, 1):
            bar.config(bg=ACCENT if i <= n else BORDER)

    def _page1(self, parent):
        frame = tk.Frame(parent, bg=BG)
        tk.Label(frame, text="Account Details", bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(10, 4))
        self.reg_user = self._field(frame, "Username")
        self.reg_email = self._field(frame, "Email (for OTP verification)")
        self._msg1 = tk.Label(frame, text="", bg=BG, fg=DANGER,
                              font=FONT_MONO, wraplength=400)
        self._msg1.pack(anchor="w", pady=4)
        self._send_otp_btn = tk.Button(
            frame, text="Send OTP to Email", command=self._p1_next)
        style_btn(self._send_otp_btn)
        self._send_otp_btn.pack(anchor="w", pady=8)

        self._reg_otp_frame = tk.Frame(frame, bg=BG)
        tk.Label(self._reg_otp_frame, text="📧  OTP sent. Enter it below:",
                 bg=BG, fg=SUCCESS, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 6))
        self._reg_otp_var = tk.StringVar()
        otp_e = tk.Entry(self._reg_otp_frame, textvariable=self._reg_otp_var,
                         width=12, justify="center", font=("Courier New", 16, "bold"))
        style_entry(otp_e)
        otp_e.pack(anchor="w", ipady=6)
        self._reg_otp_msg = tk.Label(self._reg_otp_frame, text="", bg=BG,
                                     fg=DANGER, font=FONT_MONO)
        self._reg_otp_msg.pack(anchor="w", pady=4)
        otp_btn_row = tk.Frame(self._reg_otp_frame, bg=BG)
        otp_btn_row.pack(anchor="w", pady=4)
        verify_btn = tk.Button(
            otp_btn_row, text="Verify & Continue ->", command=self._p1_verify_otp)
        style_btn(verify_btn)
        verify_btn.pack(side="left", padx=(0, 8))
        resend_btn = tk.Button(
            otp_btn_row, text="Resend OTP", command=self._p1_next)
        style_btn(resend_btn, color=SURFACE2, fg=TEXT)
        resend_btn.pack(side="left")
        return frame

    def _page2(self, parent):
        frame = tk.Frame(parent, bg=BG)
        tk.Label(frame, text="Upload Image & Select Secret Points", bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(10, 2))
        tk.Label(frame, text="Upload a personal image, then click 3-5 secret spots.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 8))
        pick_btn = tk.Button(frame, text="Choose Image File",
                             command=self._pick_image)
        style_btn(pick_btn, color=SURFACE2, fg=TEXT)
        pick_btn.pack(anchor="w", pady=(0, 8))
        self.img_canvas = ImageClickCanvas(
            frame, max_w=520, max_h=300, stealth_mode=False)
        self.img_canvas.pack(fill="x")
        btn_row = tk.Frame(frame, bg=BG)
        btn_row.pack(fill="x", pady=8)
        reset_btn = tk.Button(btn_row, text="Reset Points",
                              command=lambda: self.img_canvas.reset())
        style_btn(reset_btn, color=SURFACE2, fg=TEXT)
        reset_btn.pack(side="left", padx=(0, 8))
        next_btn = tk.Button(btn_row, text="Continue ->",
                             command=self._p2_next)
        style_btn(next_btn)
        next_btn.pack(side="left")
        self._msg2 = tk.Label(frame, text="", bg=BG, fg=DANGER, font=FONT_MONO)
        self._msg2.pack(anchor="w")
        return frame

    def _page3(self, parent):
        frame = tk.Frame(parent, bg=BG)
        tk.Label(frame, text="Confirm Registration", bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(10, 8))
        box = tk.Frame(frame, bg=SURFACE, padx=16, pady=14)
        box.pack(fill="x", pady=(0, 12))
        self._confirm = {}
        for key in ["Username", "Email", "Click Points", "Storage"]:
            row = tk.Frame(box, bg=SURFACE)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{key}:", bg=SURFACE, fg=MUTED,
                     font=("Courier New", 9), width=14, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="--", bg=SURFACE, fg=TEXT,
                           font=("Courier New", 9), anchor="w")
            lbl.pack(side="left")
            self._confirm[key] = lbl
        self._msg3 = tk.Label(frame, text="", bg=BG, fg=DANGER, font=FONT_MONO)
        self._msg3.pack(anchor="w", pady=4)
        btn_row = tk.Frame(frame, bg=BG)
        btn_row.pack(fill="x", pady=4)
        back_btn = tk.Button(btn_row, text="<- Back",
                             command=lambda: self._show_page(2))
        style_btn(back_btn, color=SURFACE2, fg=TEXT)
        back_btn.pack(side="left", padx=(0, 8))
        reg_btn = tk.Button(
            btn_row, text="Complete Registration", command=self._do_register)
        style_btn(reg_btn)
        reg_btn.pack(side="left")
        return frame

    def _field(self, parent, label_text):
        tk.Label(parent, text=label_text, bg=BG, fg=MUTED,
                 font=("Courier New", 9, "bold")).pack(anchor="w", pady=(8, 2))
        var = tk.StringVar()
        entry = tk.Entry(parent, textvariable=var, width=36)
        style_entry(entry)
        entry.pack(anchor="w", ipady=6)
        return var

    def _pick_image(self):
        path = filedialog.askopenfilename(
            title="Select your secret image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif")]
        )
        if not path:
            return
        self.pil_image = Image.open(path).convert("RGB")
        self.img_canvas.load_image(self.pil_image)

    def _p1_next(self):
        u = self.reg_user.get().strip()
        e = self.reg_email.get().strip()
        if not u or not e:
            self._msg1.config(text="Please fill in all fields.")
            return
        if "@" not in e or "." not in e:
            self._msg1.config(text="Enter a valid email address.")
            return
        if db_user_exists(u):
            self._msg1.config(text="Username already taken.")
            return
        otp, expiry = generate_otp()
        self._reg_otp = otp
        self._reg_otp_expiry = expiry
        self._email_verified = False
        send_otp_email(e, otp)
        masked = e[:3] + "***" + e[e.index("@"):]
        self._msg1.config(text=f"OTP sent to {masked}", fg=SUCCESS)
        self._reg_otp_var.set("")
        self._reg_otp_msg.config(text="")
        self._reg_otp_frame.pack(anchor="w", pady=(4, 0))

    def _p1_verify_otp(self):
        if time.time() > self._reg_otp_expiry:
            self._reg_otp_msg.config(text="OTP expired. Click 'Resend OTP'.")
            return
        code = self._reg_otp_var.get().strip()
        if len(code) != 6:
            self._reg_otp_msg.config(text="Enter the full 6-digit OTP.")
            return
        if not hmac.compare_digest(self._reg_otp, code):
            self._reg_otp_msg.config(text="Invalid OTP. Try again.")
            self._reg_otp_var.set("")
            return
        self._email_verified = True
        self._reg_otp_frame.pack_forget()
        self._msg1.config(text="✅ Email verified!", fg=SUCCESS)
        self._show_page(2)

    def _p2_next(self):
        if self.pil_image is None:
            self._msg2.config(text="Please upload an image first.")
            return
        clicks = self.img_canvas.get_clicks()
        if len(clicks) < 3:
            self._msg2.config(
                text="Select at least 3 secret points on the image.")
            return
        self._msg2.config(text="")
        self._confirm["Username"].config(
            text=self.reg_user.get().strip(), fg=ACCENT)
        self._confirm["Email"].config(text=self.reg_email.get().strip())
        self._confirm["Click Points"].config(
            text=f"{len(clicks)} points selected", fg=SUCCESS)
        self._confirm["Storage"].config(
            text="MySQL  (imagevault database)", fg=ACCENT2)
        self._show_page(3)

    def _do_register(self):
        username = self.reg_user.get().strip().lower()
        email = self.reg_email.get().strip()
        clicks = self.img_canvas.get_clicks()
        img_hash = compute_phash(self.pil_image)
        w, h = self.pil_image.size
        norm = [normalize_point(x, y, w, h) for x, y in clicks]
        try:
            db_create_user(username, email, img_hash, w, h, norm)
        except Error as e:
            self._msg3.config(text=f"Database error: {e}")
            return
        messagebox.showinfo(
            "Success", f"Account created for '{username}'!\nYou can now sign in.")
        self.app.show("login")

    def on_show(self):
        self.reg_user.set("")
        self.reg_email.set("")
        self.pil_image = None
        self._reg_otp = None
        self._reg_otp_expiry = 0
        self._email_verified = False
        self.img_canvas.reset()
        self._reg_otp_frame.pack_forget()
        self._show_page(1)
        self._msg1.config(text="", fg=DANGER)
        self._msg2.config(text="")


# ─────────────────────────────────────────────────────────
#  LOGIN SCREEN
# ─────────────────────────────────────────────────────────

class LoginScreen(Screen):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._pending_user = None
        self._otp = None
        self._otp_expiry = 0
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=30, pady=(20, 10))
        tk.Button(hdr, text="<- Back", command=lambda: self.app.show("welcome"),
                  bg=BG, fg=MUTED, relief="flat", cursor="hand2",
                  font=("Segoe UI", 10)).pack(side="left")
        tk.Label(hdr, text="Sign In", bg=BG, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=16)

        self._pages = {}
        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True, padx=30, pady=0)
        self._pages["image"] = self._page_image(container)
        self._pages["otp"] = self._page_otp(container)
        self._pages["recovery"] = self._page_recovery(container)
        self._show_page("image")

    def _show_page(self, name):
        for f in self._pages.values():
            f.pack_forget()
        self._pages[name].pack(fill="both", expand=True)

    def _page_image(self, parent):
        frame = tk.Frame(parent, bg=BG)
        tk.Label(frame, text="Step 1 -- Upload your secret image and click your points",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 8))
        tk.Label(frame, text="USERNAME", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", pady=(4, 2))
        self.login_user = tk.StringVar()
        uentry = tk.Entry(frame, textvariable=self.login_user, width=32)
        style_entry(uentry)
        uentry.pack(anchor="w", ipady=6)
        tk.Label(frame, text="SECRET IMAGE", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", pady=(12, 4))
        self._login_pil = None
        pick_btn = tk.Button(frame, text="Choose Image File",
                             command=self._pick_login_image)
        style_btn(pick_btn, color=SURFACE2, fg=TEXT)
        pick_btn.pack(anchor="w")
        note = tk.Frame(frame, bg="#ffffff", relief="solid",
                        bd=1, padx=10, pady=6)
        note.pack(fill="x", pady=(8, 0))
        tk.Label(note, text="Stealth Mode ON -- image is blurred. Hold 'Reveal' to peek.",
                 bg="#FFFFFF", fg=WARNING, font=("Courier New", 8),
                 wraplength=480, justify="left").pack(anchor="w")
        self.login_canvas = ImageClickCanvas(
            frame, max_w=520, max_h=260, stealth_mode=True)
        self.login_canvas.pack(fill="x", pady=(6, 0))
        self._login_msg = tk.Label(
            frame, text="", bg=BG, fg=DANGER, font=FONT_MONO)
        self._login_msg.pack(anchor="w", pady=4)
        btn_row = tk.Frame(frame, bg=BG)
        btn_row.pack(fill="x", pady=4)

        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.pack(pady=0.5)

        # create frame
        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.pack(pady=0.5)

# Reset button
        reset_btn = tk.Button(btn_frame, text="Reset Points",
                              command=self._reset_login)
        style_btn(reset_btn)
        reset_btn.pack(side="left", padx=8)

# Forgot button (keep it like link)
        forgot_btn = tk.Button(btn_frame, text="Forgot image?",
                               command=lambda: self._show_page("recovery"),
                               bg=BG, fg=MUTED, relief="solid", bd=1,
                               cursor="hand2",
                               font=("Segoe UI", 9, "underline"))
        forgot_btn.pack(side="left", padx=20)

# Verify button
        verify_btn = tk.Button(btn_frame, text="Verify Image & Points ->",
                               command=self._verify_image)
        style_btn(verify_btn)
        verify_btn.pack(side="left", padx=20)

        return frame

    def _page_otp(self, parent):
        frame = tk.Frame(parent, bg=BG)
        tk.Label(frame, text="Image & click pattern verified!",
                 bg=BG, fg=SUCCESS, font=("Segoe UI", 11, "bold")).pack(pady=(20, 4))
        tk.Label(frame, text="Step 2 -- Enter the 6-digit OTP",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(pady=(0, 20))
        email_box = tk.Frame(frame, bg=SURFACE, padx=16, pady=12)
        email_box.pack(pady=(0, 16))
        tk.Label(email_box, text="📧  A 6-digit OTP has been sent to your registered email.",
                 bg=SURFACE, fg=SUCCESS, font=("Segoe UI", 10, "bold")).pack()
        self._otp_email_hint = tk.Label(email_box, text="", bg=SURFACE, fg=MUTED,
                                        font=("Courier New", 9))
        self._otp_email_hint.pack(pady=(4, 0))
        self._otp_timer = tk.Label(email_box, text="Expires in: 5:00",
                                   bg=SURFACE, fg=MUTED, font=("Courier New", 9))
        self._otp_timer.pack()
        otp_row = tk.Frame(frame, bg=BG)
        otp_row.pack(pady=(0, 16))
        self._otp_vars = []
        self._otp_entries = []
        for i in range(6):
            v = tk.StringVar()
            e = tk.Entry(otp_row, textvariable=v, width=3, justify="center",
                         font=("Courier New", 18, "bold"),
                         bg=SURFACE2, fg=TEXT, insertbackground=ACCENT,
                         relief="flat", highlightthickness=2,
                         highlightbackground=BORDER, highlightcolor=ACCENT)
            e.pack(side="left", padx=3, ipady=8)
            self._otp_vars.append(v)
            self._otp_entries.append(e)
            v.trace_add("write", lambda *a, idx=i: self._otp_typed(idx))
        self._otp_msg = tk.Label(
            frame, text="", bg=BG, fg=DANGER, font=FONT_MONO)
        self._otp_msg.pack(pady=4)
        verify_btn = tk.Button(
            frame, text="Enter Vault ->", command=self._verify_otp)
        style_btn(verify_btn)
        verify_btn.pack()
        tk.Button(frame, text="<- Start over", command=self._reset_login,
                  bg=BG, fg=MUTED, relief="flat", cursor="hand2",
                  font=("Segoe UI", 9)).pack(pady=(12, 0))
        return frame

    def _page_recovery(self, parent):
        frame = tk.Frame(parent, bg=BG)
        tk.Button(frame, text="<- Back to login", command=lambda: self._show_page("image"),
                  bg=BG, fg=MUTED, relief="flat", cursor="hand2",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(10, 16))
        tk.Label(frame, text="Account Recovery", bg=BG, fg=TEXT,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(frame, text="Enter your email to receive a recovery OTP.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 12))
        tk.Label(frame, text="EMAIL", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", pady=(0, 2))
        self._rec_email = tk.StringVar()
        e = tk.Entry(frame, textvariable=self._rec_email, width=36)
        style_entry(e)
        e.pack(anchor="w", ipady=6)
        self._rec_msg = tk.Label(frame, text="", bg=BG, fg=MUTED,
                                 font=FONT_MONO, wraplength=400, justify="left")
        self._rec_msg.pack(anchor="w", pady=8)
        btn = tk.Button(frame, text="Send Recovery OTP",
                        command=self._do_recovery)
        style_btn(btn)
        btn.pack(anchor="w")
        self._rec_otp_frame = tk.Frame(frame, bg=BG)
        tk.Label(self._rec_otp_frame, text="ENTER OTP", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", pady=(8, 2))
        self._rec_otp_var = tk.StringVar()
        otp_e = tk.Entry(self._rec_otp_frame, textvariable=self._rec_otp_var,
                         width=12, justify="center", font=("Courier New", 16, "bold"))
        style_entry(otp_e)
        otp_e.pack(anchor="w", ipady=6)
        self._rec_otp_msg = tk.Label(self._rec_otp_frame, text="", bg=BG,
                                     fg=DANGER, font=FONT_MONO)
        self._rec_otp_msg.pack(anchor="w", pady=4)
        verify_btn = tk.Button(self._rec_otp_frame, text="Verify & Enter Vault",
                               command=self._verify_recovery_otp)
        style_btn(verify_btn)
        verify_btn.pack(anchor="w")
        return frame

    def _pick_login_image(self):
        path = filedialog.askopenfilename(
            title="Select your secret image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")]
        )
        if not path:
            return
        self._login_pil = Image.open(path).convert("RGB")
        self.login_canvas.load_image(self._login_pil)

    def _verify_image(self):
        username = self.login_user.get().strip().lower()
        if not username:
            self._login_msg.config(text="Enter your username.")
            return
        if self._login_pil is None:
            self._login_msg.config(text="Upload your secret image.")
            return
        clicks = self.login_canvas.get_clicks()
        if not clicks:
            self._login_msg.config(
                text="Click your secret points on the image.")
            return
        user = db_get_user(username)
        if not user:
            self._login_msg.config(text="Username not found.")
            return
        if not images_match(user["image_hash"], compute_phash(self._login_pil)):
            self._login_msg.config(text="Image does not match. Try again.")
            return
        w, h = self._login_pil.size
        norm = [normalize_point(x, y, w, h) for x, y in clicks]
        if not clicks_match(json.loads(user["clicks"]), norm):
            self._login_msg.config(text="Click pattern does not match.")
            return
        self._login_msg.config(text="")
        otp, expiry = generate_otp()
        self._otp = otp
        self._otp_expiry = expiry
        self._pending_user = user
        masked = user["email"][:3] + "***" + \
            user["email"][user["email"].index("@"):]
        self._otp_email_hint.config(text=f"Sent to: {masked}")
        send_otp_email(user["email"], otp)
        self._show_page("otp")
        self._tick_timer()
        self._otp_entries[0].focus_set()

    def _tick_timer(self):
        remaining = int(self._otp_expiry - time.time())
        if remaining <= 0:
            self._otp_timer.config(text="OTP Expired!", fg=DANGER)
            return
        m, s = divmod(remaining, 60)
        self._otp_timer.config(text=f"Expires in: {m}:{s:02d}", fg=MUTED)
        self.after(1000, self._tick_timer)

    def _otp_typed(self, idx):
        val = self._otp_vars[idx].get()
        if len(val) > 1:
            self._otp_vars[idx].set(val[-1])
        if val and idx < 5:
            self._otp_entries[idx + 1].focus_set()
        if len("".join(v.get() for v in self._otp_vars)) == 6:
            self.after(100, self._verify_otp)

    def _verify_otp(self):
        if time.time() > self._otp_expiry:
            self._otp_msg.config(text="OTP has expired. Please start over.")
            return
        code = "".join(v.get() for v in self._otp_vars)
        if len(code) != 6:
            self._otp_msg.config(text="Enter all 6 digits.")
            return
        if not hmac.compare_digest(self._otp, code):
            self._otp_msg.config(text="Invalid OTP. Try again.")
            for v in self._otp_vars:
                v.set("")
            self._otp_entries[0].focus_set()
            return
        self.app.logged_in_user = self._pending_user
        self.app.show("vault")

    def _do_recovery(self):
        email = self._rec_email.get().strip()
        user = db_get_user_by_email(email)
        if not user:
            self._rec_msg.config(text="Email not found.", fg=DANGER)
            self._rec_otp_frame.pack_forget()
            return
        otp, expiry = generate_otp()
        self._rec_otp = otp
        self._rec_otp_expiry = expiry
        self._rec_pending_user = user
        send_otp_email(email, otp)
        masked = email[:3] + "***" + email[email.index("@"):]
        self._rec_msg.config(
            text=f"Recovery OTP sent to {masked}.", fg=SUCCESS)
        self._rec_otp_var.set("")
        self._rec_otp_msg.config(text="")
        self._rec_otp_frame.pack(anchor="w", pady=(4, 0))

    def _verify_recovery_otp(self):
        if time.time() > self._rec_otp_expiry:
            self._rec_otp_msg.config(text="OTP has expired. Please resend.")
            return
        code = self._rec_otp_var.get().strip()
        if len(code) != 6:
            self._rec_otp_msg.config(text="Enter the full 6-digit OTP.")
            return
        if not hmac.compare_digest(self._rec_otp, code):
            self._rec_otp_msg.config(text="Invalid OTP. Try again.")
            self._rec_otp_var.set("")
            return
        self.app.logged_in_user = self._rec_pending_user
        self.app.show("vault")

    def _reset_login(self):
        self._login_pil = None
        self._pending_user = None
        self.login_user.set("")
        self.login_canvas.reset()
        self._login_msg.config(text="")
        for v in self._otp_vars:
            v.set("")
        self._show_page("image")

    def on_show(self):
        self._reset_login()


# ─────────────────────────────────────────────────────────
#  FOLDER DIALOG  (create / rename)
# ─────────────────────────────────────────────────────────

class FolderDialog(tk.Toplevel):
    """Modal dialog for creating or renaming a folder."""

    def __init__(self, parent, title="New Folder", initial_name="",
                 initial_icon="📁", initial_color="#b30000", on_save=None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG)
        self.geometry("380x320")
        self.resizable(False, False)
        self.grab_set()
        self.on_save = on_save

        tk.Label(self, text=title, bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(pady=(20, 12))

        # Name
        tk.Label(self, text="FOLDER NAME", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", padx=24, pady=(0, 2))
        self._name_var = tk.StringVar(value=initial_name)
        name_e = tk.Entry(self, textvariable=self._name_var, width=36)
        style_entry(name_e)
        name_e.pack(anchor="w", padx=24, ipady=5)
        name_e.focus_set()

        # Icon picker
        tk.Label(self, text="ICON", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", padx=24, pady=(10, 4))
        icon_row = tk.Frame(self, bg=BG)
        icon_row.pack(anchor="w", padx=24)
        self._icon_var = tk.StringVar(value=initial_icon)
        for ic in FOLDER_ICONS:
            rb = tk.Radiobutton(icon_row, text=ic, variable=self._icon_var, value=ic,
                                bg=BG, activebackground=BG, fg=TEXT,
                                font=("Segoe UI", 14), indicatoron=False,
                                relief="flat", padx=4, pady=2, cursor="hand2")
            rb.pack(side="left", padx=2)

        # Color picker
        tk.Label(self, text="COLOR", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", padx=24, pady=(10, 4))
        color_row = tk.Frame(self, bg=BG)
        color_row.pack(anchor="w", padx=24)
        self._color_var = tk.StringVar(value=initial_color)
        for c in FOLDER_COLORS:
            rb = tk.Radiobutton(color_row, variable=self._color_var, value=c,
                                bg=c, activebackground=c, selectcolor=c,
                                indicatoron=False, width=3, height=1,
                                relief="solid", bd=2, cursor="hand2")
            rb.pack(side="left", padx=3)

        self._msg = tk.Label(self, text="", bg=BG, fg=DANGER, font=FONT_MONO)
        self._msg.pack(pady=4)

        save_btn = tk.Button(self, text="Save Folder", command=self._save)
        style_btn(save_btn)
        save_btn.pack(pady=4)

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            self._msg.config(text="Please enter a folder name.")
            return
        if self.on_save:
            self.on_save(name, self._icon_var.get(), self._color_var.get())
        self.destroy()

# ─────────────────────────────────────────────────────────
#  VAULT SCREEN  (main screen with folder sidebar)
# ─────────────────────────────────────────────────────────


class VaultScreen(Screen):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._active_folder_id = None   # None = "All Items"
        self._active_tab = "passwords"
        self._build()

    def _build(self):
        # ── Top bar ──────────────────────────────────────────
        topbar = tk.Frame(self, bg=SURFACE, pady=10)
        topbar.pack(fill="x")
        tk.Label(topbar, text="ImageVault", bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=20)
        self._user_label = tk.Label(topbar, text="", bg=SURFACE, fg=MUTED,
                                    font=("Courier New", 9))
        self._user_label.pack(side="left", padx=8)
        tk.Label(topbar, bg=SURFACE, fg=SUCCESS,
                 font=("Courier New", 8)).pack(side="left", padx=8)
        tk.Button(topbar, text="Logout", command=self._logout,
                  bg=SURFACE, fg=MUTED, relief="flat", cursor="hand2",
                  font=("Segoe UI", 9)).pack(side="right", padx=16)

        # ── Main body: sidebar + content ─────────────────────
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # Left sidebar (folders)
        self._sidebar = tk.Frame(body, bg=SURFACE2, width=190)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)
        self._build_sidebar()

        # Right content area
        content_wrap = tk.Frame(body, bg=BG)
        content_wrap.pack(side="left", fill="both", expand=True)

        # Tab bar
        tab_bar = tk.Frame(content_wrap, bg=SURFACE, pady=0)
        tab_bar.pack(fill="x")
        self._tab_btns = {}
        for tab_id, label in [("passwords", "🔑 Passwords"),
                              ("notes",     "📝 Notes"),
                              ("secrets",   "🔒 Secret Texts")]:
            btn = tk.Button(tab_bar, text=label,
                            command=lambda t=tab_id: self._switch_tab(t),
                            bg=SURFACE, fg=MUTED, relief="flat", cursor="hand2",
                            font=("Courier New", 10, "bold"), padx=16, pady=10,
                            activebackground=BG, activeforeground=TEXT)
            btn.pack(side="left")
            self._tab_btns[tab_id] = btn

        # Action row (search + add)
        action_row = tk.Frame(content_wrap, bg=BG, pady=6)
        action_row.pack(fill="x", padx=16)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._refresh_list())
        search = tk.Entry(action_row, textvariable=self._search_var, width=28)
        style_entry(search)
        search.pack(side="left", ipady=6)
        tk.Label(action_row, text=" Search", bg=BG, fg=MUTED,
                 font=("Segoe UI", 10)).pack(side="left")
        self._add_btn = tk.Button(
            action_row, text="+ Add", command=self._open_add_dialog)
        style_btn(self._add_btn)
        self._add_btn.pack(side="right")

        # Folder context label
        self._folder_label = tk.Label(content_wrap, text="All Items",
                                      bg=BG, fg=ACCENT,
                                      font=("Courier New", 10, "bold"), anchor="w")
        self._folder_label.pack(fill="x", padx=16, pady=(0, 2))

        # Scrollable list
        list_frame = tk.Frame(content_wrap, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        self._canvas = tk.Canvas(list_frame, bg=BG, bd=0,
                                 highlightthickness=0, yscrollcommand=scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._canvas.yview)
        self._inner = tk.Frame(self._canvas, bg=BG)
        self._cw = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>",
                         lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._cw, width=e.width))

        self._pw_msg = tk.Label(content_wrap, text="",
                                bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self._pw_msg.pack()

    # ── Sidebar ──────────────────────────────────────────────

    def _build_sidebar(self):
        for w in self._sidebar.winfo_children():
            w.destroy()

        tk.Label(self._sidebar, text="FOLDERS", bg=SURFACE2, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", padx=12, pady=(14, 4))

        # "All Items" row
        all_btn = tk.Button(self._sidebar, text="  📂  All Items",
                            command=lambda: self._select_folder(None),
                            bg=ACCENT if self._active_folder_id is None else SURFACE2,
                            fg="#fff" if self._active_folder_id is None else TEXT,
                            relief="flat", anchor="w", cursor="hand2",
                            font=("Courier New", 10, "bold"), pady=8, padx=6)
        all_btn.pack(fill="x", padx=8, pady=2)

        # Per-folder rows
        user = self.app.logged_in_user
        if user:
            folders = db_get_folders(user["id"])
            for f in folders:
                self._make_folder_row(f)

        # New folder button
        sep = tk.Frame(self._sidebar, bg=BORDER, height=1)
        sep.pack(fill="x", padx=8, pady=8)
        new_btn = tk.Button(self._sidebar, text="  +  New Folder",
                            command=self._create_folder,
                            bg=SURFACE2, fg=ACCENT, relief="flat", anchor="w",
                            cursor="hand2", font=("Courier New", 10, "bold"),
                            pady=8, padx=6)
        new_btn.pack(fill="x", padx=8)

    def _make_folder_row(self, f):
        is_active = self._active_folder_id == f["id"]
        row = tk.Frame(self._sidebar,
                       bg=f["color"] if is_active else SURFACE2,
                       cursor="hand2")
        row.pack(fill="x", padx=8, pady=2)

        lbl = tk.Button(row,
                        text=f"  {f['icon']}  {f['name']}",
                        command=lambda fid=f["id"]: self._select_folder(fid),
                        bg=f["color"] if is_active else SURFACE2,
                        fg="#fff" if is_active else TEXT,
                        relief="flat", anchor="w", cursor="hand2",
                        font=("Courier New", 10, "bold"), pady=7, padx=4)
        lbl.pack(side="left", fill="x", expand=True)

        # Three-dot menu
        menu_btn = tk.Button(row, text="⋯",
                             bg=f["color"] if is_active else SURFACE2,
                             fg="#fff" if is_active else MUTED,
                             relief="flat", cursor="hand2",
                             font=("Courier New", 10), padx=4, pady=7)
        menu_btn.pack(side="right")
        menu_btn.bind("<Button-1>",
                      lambda e, folder=f: self._folder_menu(e, folder))

    def _folder_menu(self, event, folder):
        menu = tk.Menu(self, tearoff=0, bg=SURFACE, fg=TEXT,
                       font=("Courier New", 10), activebackground=ACCENT,
                       activeforeground="#fff", bd=1, relief="solid")
        menu.add_command(label="  ✏️  Rename",
                         command=lambda: self._rename_folder(folder))
        menu.add_separator()
        menu.add_command(label="  🗑️  Delete Folder",
                         command=lambda: self._delete_folder(folder))
        menu.tk_popup(event.x_root, event.y_root)

    def _select_folder(self, folder_id):
        self._active_folder_id = folder_id
        self._build_sidebar()
        self._update_folder_label()
        self._refresh_list()

    def _update_folder_label(self):
        if self._active_folder_id is None:
            self._folder_label.config(text="All Items")
        else:
            user = self.app.logged_in_user
            folders = db_get_folders(user["id"])
            for f in folders:
                if f["id"] == self._active_folder_id:
                    self._folder_label.config(text=f"{f['icon']}  {f['name']}")
                    break

    def _create_folder(self):
        user = self.app.logged_in_user

        def save(name, icon, color):
            db_create_folder(user["id"], name, icon, color)
            self._build_sidebar()
        FolderDialog(self, title="New Folder", on_save=save)

    def _rename_folder(self, folder):
        def save(name, icon, color):
            db_rename_folder(folder["id"], name)
            if self._active_folder_id == folder["id"]:
                self._update_folder_label()
            self._build_sidebar()
        FolderDialog(self, title="Rename Folder",
                     initial_name=folder["name"],
                     initial_icon=folder["icon"],
                     initial_color=folder["color"],
                     on_save=save)

    def _delete_folder(self, folder):
        pw, nt, st = db_folder_item_counts(folder["id"])
        total = pw + nt + st
        msg = f"Delete folder '{folder['name']}'?"
        if total > 0:
            msg += f"\n\n{total} item(s) inside will be moved to 'All Items' (unfiled)."
        if messagebox.askyesno("Delete Folder", msg):
            db_delete_folder(folder["id"])
            if self._active_folder_id == folder["id"]:
                self._active_folder_id = None
            self._build_sidebar()
            self._update_folder_label()
            self._refresh_list()

    # ── Tabs ─────────────────────────────────────────────────

    def _switch_tab(self, tab_id):
        self._active_tab = tab_id
        for t, btn in self._tab_btns.items():
            btn.config(bg=BG if t == tab_id else SURFACE,
                       fg=ACCENT if t == tab_id else MUTED,
                       relief="groove" if t == tab_id else "flat")
        labels = {"passwords": "+ Add Password",
                  "notes":     "+ Add Note",
                  "secrets":   "+ Add Secret Text"}
        self._add_btn.config(text=labels[tab_id])
        self._refresh_list()

    # ── List refresh ─────────────────────────────────────────

    def _refresh_list(self):
        for w in self._inner.winfo_children():
            w.destroy()
        user = self.app.logged_in_user
        if not user:
            return
        q = self._search_var.get().lower()
        fid = self._active_folder_id

        if self._active_tab == "passwords":
            items = db_get_passwords(user["id"], fid)
            items = [p for p in items
                     if q in p["site"].lower() or q in (p["username"] or "").lower()]
            if not items:
                self._empty_label("No passwords stored here.")
            else:
                for p in items:
                    self._make_pw_row(p)

        elif self._active_tab == "notes":
            items = db_get_notes(user["id"], fid)
            items = [n for n in items
                     if q in n["title"].lower() or q in n["content"].lower()]
            if not items:
                self._empty_label("No notes stored here.")
            else:
                for n in items:
                    self._make_note_row(n)

        elif self._active_tab == "secrets":
            items = db_get_secret_texts(user["id"], fid)
            items = [s for s in items
                     if q in s["label"].lower() or q in s["content"].lower()]
            if not items:
                self._empty_label("No secret texts stored here.")
            else:
                for s in items:
                    self._make_secret_row(s)

    def _empty_label(self, msg):
        tk.Label(self._inner, text=msg + "\nClick '+ Add' to start.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10), justify="center").pack(pady=40)

    # ── Password rows ─────────────────────────────────────────

    def _make_pw_row(self, p):
        row = tk.Frame(self._inner, bg=SURFACE, pady=10, padx=14)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=self._site_icon(p["site"]), bg=SURFACE,
                 font=("Segoe UI", 16), width=3).pack(side="left")
        info = tk.Frame(row, bg=SURFACE)
        info.pack(side="left", padx=10, fill="x", expand=True)
        tk.Label(info, text=p["site"], bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        tk.Label(info, text=p["username"] or "--", bg=SURFACE, fg=MUTED,
                 font=("Courier New", 9), anchor="w").pack(fill="x")

        pw_frame = tk.Frame(row, bg=SURFACE2, padx=8, pady=4)
        pw_frame.pack(side="left", padx=8)
        pw_var = tk.StringVar(value="••••••••")
        pw_lbl = tk.Label(pw_frame, textvariable=pw_var, bg=SURFACE2, fg=MUTED,
                          font=("Courier New", 10), width=16)
        pw_lbl.pack(side="left")
        visible = [False]

        def toggle(lbl=pw_lbl, var=pw_var, pw=p["password"]):
            visible[0] = not visible[0]
            var.set(pw if visible[0] else "••••••••")
            lbl.config(fg=TEXT if visible[0] else MUTED)
        tk.Button(pw_frame, text="Show", command=toggle, bg=SURFACE2, fg=MUTED,
                  relief="flat", cursor="hand2", font=("Segoe UI", 9)).pack(side="left", padx=2)

        def copy_pw(pw=p["password"]):
            self.clipboard_clear()
            self.clipboard_append(pw)
            self._pw_msg.config(text="Password copied!", fg=SUCCESS)
            self.after(2500, lambda: self._pw_msg.config(text=""))
        tk.Button(pw_frame, text="Copy", command=copy_pw, bg=SURFACE2, fg=MUTED,
                  relief="flat", cursor="hand2", font=("Segoe UI", 9)).pack(side="left")

        # Move-to-folder button
        self._move_btn(row, "pw", p)

        def delete(pw_id=p["id"], site=p["site"]):
            if messagebox.askyesno("Delete", f"Delete password for '{site}'?"):
                db_delete_password(pw_id)
                self._refresh_list()
        tk.Button(row, text="Delete", command=delete, bg=DANGER, fg="#fff",
                  relief="flat", cursor="hand2",
                  font=("Courier New", 9, "bold"), padx=6, pady=4).pack(side="right")

    # ── Note rows ─────────────────────────────────────────────

    def _make_note_row(self, n):
        row = tk.Frame(self._inner, bg=SURFACE, pady=10, padx=14)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="📝", bg=SURFACE, font=(
            "Segoe UI", 16), width=3).pack(side="left")
        info = tk.Frame(row, bg=SURFACE)
        info.pack(side="left", padx=10, fill="x", expand=True)
        tk.Label(info, text=n["title"], bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        preview = n["content"][:80].replace(
            "\n", " ") + ("…" if len(n["content"]) > 80 else "")
        tk.Label(info, text=preview, bg=SURFACE, fg=MUTED,
                 font=("Courier New", 9), anchor="w", wraplength=340,
                 justify="left").pack(fill="x")

        view_btn = tk.Button(row, text="View",
                             command=lambda: self._view_note(n),
                             bg=SURFACE2, fg=TEXT, relief="flat", cursor="hand2",
                             font=("Courier New", 9, "bold"), padx=6, pady=4)
        view_btn.pack(side="left", padx=4)

        self._move_btn(row, "note", n)

        def delete(nid=n["id"], title=n["title"]):
            if messagebox.askyesno("Delete", f"Delete note '{title}'?"):
                db_delete_note(nid)
                self._refresh_list()
        tk.Button(row, text="Delete", command=delete, bg=DANGER, fg="#fff",
                  relief="flat", cursor="hand2",
                  font=("Courier New", 9, "bold"), padx=6, pady=4).pack(side="right")

    def _view_note(self, n):
        dlg = tk.Toplevel(self)
        dlg.title(f"Note – {n['title']}")
        dlg.configure(bg=BG)
        dlg.geometry("480x380")
        tk.Label(dlg, text=n["title"], bg=BG, fg=ACCENT,
                 font=("Courier New", 14, "bold")).pack(anchor="w", padx=24, pady=(20, 8))
        txt = tk.Text(dlg, bg=SURFACE2, fg=TEXT, font=("Courier New", 11),
                      relief="solid", bd=1, wrap="word", padx=8, pady=8)
        txt.insert("1.0", n["content"])
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=24, pady=(0, 20))

    # ── Secret text rows ──────────────────────────────────────

    def _make_secret_row(self, s):
        row = tk.Frame(self._inner, bg=SURFACE, pady=10, padx=14)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="🔒", bg=SURFACE, font=(
            "Segoe UI", 16), width=3).pack(side="left")
        info = tk.Frame(row, bg=SURFACE)
        info.pack(side="left", padx=10, fill="x", expand=True)
        tk.Label(info, text=s["label"], bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")

        visible = [False]
        preview_var = tk.StringVar(value="•" * min(len(s["content"]), 40))
        preview_lbl = tk.Label(info, textvariable=preview_var, bg=SURFACE, fg=MUTED,
                               font=("Courier New", 9), anchor="w", wraplength=300)
        preview_lbl.pack(fill="x")

        def toggle_secret():
            visible[0] = not visible[0]
            if visible[0]:
                preview_var.set(s["content"][:120] +
                                ("…" if len(s["content"]) > 120 else ""))
                preview_lbl.config(fg=TEXT)
                show_btn.config(text="Hide")
            else:
                preview_var.set("•" * min(len(s["content"]), 40))
                preview_lbl.config(fg=MUTED)
                show_btn.config(text="Show")

        show_btn = tk.Button(row, text="Show", command=toggle_secret,
                             bg=SURFACE2, fg=TEXT, relief="flat", cursor="hand2",
                             font=("Courier New", 9, "bold"), padx=6, pady=4)
        show_btn.pack(side="left", padx=4)

        def copy_secret(content=s["content"]):
            self.clipboard_clear()
            self.clipboard_append(content)
            self._pw_msg.config(text="Copied to clipboard!", fg=SUCCESS)
            self.after(2500, lambda: self._pw_msg.config(text=""))
        tk.Button(row, text="Copy", command=copy_secret,
                  bg=SURFACE2, fg=MUTED, relief="flat", cursor="hand2",
                  font=("Segoe UI", 9)).pack(side="left", padx=2)

        self._move_btn(row, "secret", s)

        def delete(sid=s["id"], label=s["label"]):
            if messagebox.askyesno("Delete", f"Delete secret '{label}'?"):
                db_delete_secret_text(sid)
                self._refresh_list()
        tk.Button(row, text="Delete", command=delete, bg=DANGER, fg="#fff",
                  relief="flat", cursor="hand2",
                  font=("Courier New", 9, "bold"), padx=6, pady=4).pack(side="right")

    # ── Move-to-folder helper ─────────────────────────────────

    def _move_btn(self, parent_row, item_type, item):
        """Drop-down menu to move an item into a folder (or unfile it)."""
        user = self.app.logged_in_user
        folders = db_get_folders(user["id"])
        if not folders:
            return

        def show_menu(event=None):
            menu = tk.Menu(self, tearoff=0, bg=SURFACE, fg=TEXT,
                           font=("Courier New", 9), activebackground=ACCENT,
                           activeforeground="#fff", bd=1, relief="solid")
            menu.add_command(label="  📂  Unfiled (All Items)",
                             command=lambda: _move(None))
            menu.add_separator()
            for f in folders:
                menu.add_command(
                    label=f"  {f['icon']}  {f['name']}",
                    command=lambda fid=f["id"]: _move(fid)
                )
            menu.tk_popup(parent_row.winfo_rootx() + parent_row.winfo_width() - 80,
                          parent_row.winfo_rooty())

        def _move(fid):
            if item_type == "pw":
                db_move_password(item["id"], fid)
            elif item_type == "note":
                db_move_note(item["id"], fid)
            elif item_type == "secret":
                db_move_secret_text(item["id"], fid)
            self._refresh_list()

        btn = tk.Button(parent_row, text="Move ▸", command=show_menu,
                        bg=SURFACE2, fg=MUTED, relief="flat", cursor="hand2",
                        font=("Courier New", 9), padx=6, pady=4)
        btn.pack(side="left", padx=2)

    # ── Add dialogs ───────────────────────────────────────────

    def _open_add_dialog(self):
        if self._active_tab == "passwords":
            self._add_password_dialog()
        elif self._active_tab == "notes":
            self._add_note_dialog()
        elif self._active_tab == "secrets":
            self._add_secret_dialog()

    def _folder_selector(self, dlg):
        """Returns (frame, get_folder_id_fn) for use inside dialogs."""
        user = self.app.logged_in_user
        folders = db_get_folders(user["id"])

        tk.Label(dlg, text="SAVE TO FOLDER (optional)", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", padx=24, pady=(8, 2))
        folder_var = tk.StringVar(value="none")
        sel_frame = tk.Frame(dlg, bg=BG)
        sel_frame.pack(anchor="w", padx=24)

        rb = tk.Radiobutton(sel_frame, text="Unfiled", variable=folder_var, value="none",
                            bg=BG, activebackground=BG, fg=TEXT, font=(
                                "Courier New", 9),
                            cursor="hand2")
        rb.pack(side="left", padx=(0, 6))
        for f in folders:
            rb = tk.Radiobutton(sel_frame, text=f"{f['icon']} {f['name']}",
                                variable=folder_var, value=str(f["id"]),
                                bg=BG, activebackground=BG, fg=TEXT, font=(
                                    "Courier New", 9),
                                cursor="hand2")
            rb.pack(side="left", padx=(0, 6))

        # Pre-select active folder
        if self._active_folder_id is not None:
            folder_var.set(str(self._active_folder_id))

        def get_folder_id():
            val = folder_var.get()
            return None if val == "none" else int(val)

        return get_folder_id

    def _add_password_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Add Password")
        dlg.configure(bg=BG)
        dlg.geometry("440x380")
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text="Add New Password", bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(pady=(20, 12))
        fields = {}
        for label in ["Website / Service", "Username / Email", "Password"]:
            tk.Label(dlg, text=label.upper(), bg=BG, fg=MUTED,
                     font=("Courier New", 8, "bold")).pack(anchor="w", padx=24, pady=(4, 2))
            var = tk.StringVar()
            e = tk.Entry(dlg, textvariable=var, width=38)
            style_entry(e)
            e.pack(anchor="w", padx=24, ipady=5)
            fields[label] = var
        get_folder_id = self._folder_selector(dlg)
        msg = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=FONT_MONO)
        msg.pack(pady=4)

        def save():
            site = fields["Website / Service"].get().strip()
            uname = fields["Username / Email"].get().strip()
            pw = fields["Password"].get().strip()
            if not site or not pw:
                msg.config(text="Site and password are required.")
                return
            try:
                db_add_password(
                    self.app.logged_in_user["id"], site, uname, pw, get_folder_id())
            except Error as e:
                msg.config(text=f"DB error: {e}")
                return
            dlg.destroy()
            self._refresh_list()
        save_btn = tk.Button(dlg, text="Save Password", command=save)
        style_btn(save_btn)
        save_btn.pack(pady=8)

    def _add_note_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Add Note")
        dlg.configure(bg=BG)
        dlg.geometry("480x420")
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text="Add New Note", bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(pady=(20, 8))
        tk.Label(dlg, text="TITLE", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", padx=24, pady=(0, 2))
        title_var = tk.StringVar()
        te = tk.Entry(dlg, textvariable=title_var, width=42)
        style_entry(te)
        te.pack(anchor="w", padx=24, ipady=5)
        tk.Label(dlg, text="CONTENT", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", padx=24, pady=(8, 2))
        txt = tk.Text(dlg, bg=SURFACE2, fg=TEXT, font=("Courier New", 10),
                      relief="solid", bd=1, wrap="word", padx=6, pady=6, height=8)
        txt.pack(fill="x", padx=24)
        get_folder_id = self._folder_selector(dlg)
        msg = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=FONT_MONO)
        msg.pack(pady=4)

        def save():
            title = title_var.get().strip()
            content = txt.get("1.0", "end").strip()
            if not title or not content:
                msg.config(text="Title and content are required.")
                return
            try:
                db_add_note(
                    self.app.logged_in_user["id"], title, content, get_folder_id())
            except Error as e:
                msg.config(text=f"DB error: {e}")
                return
            dlg.destroy()
            self._refresh_list()
        save_btn = tk.Button(dlg, text="Save Note", command=save)
        style_btn(save_btn)
        save_btn.pack(pady=8)

    def _add_secret_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Add Secret Text")
        dlg.configure(bg=BG)
        dlg.geometry("480x400")
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text="Add Secret Text", bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(pady=(20, 8))
        tk.Label(dlg, text="LABEL", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", padx=24, pady=(0, 2))
        label_var = tk.StringVar()
        le = tk.Entry(dlg, textvariable=label_var, width=42)
        style_entry(le)
        le.pack(anchor="w", padx=24, ipady=5)
        tk.Label(dlg, text="SECRET CONTENT", bg=BG, fg=MUTED,
                 font=("Courier New", 8, "bold")).pack(anchor="w", padx=24, pady=(8, 2))
        txt = tk.Text(dlg, bg=SURFACE2, fg=TEXT, font=("Courier New", 10),
                      relief="solid", bd=1, wrap="word", padx=6, pady=6, height=7)
        txt.pack(fill="x", padx=24)
        get_folder_id = self._folder_selector(dlg)
        msg = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=FONT_MONO)
        msg.pack(pady=4)

        def save():
            label = label_var.get().strip()
            content = txt.get("1.0", "end").strip()
            if not label or not content:
                msg.config(text="Label and content are required.")
                return
            try:
                db_add_secret_text(
                    self.app.logged_in_user["id"], label, content, get_folder_id())
            except Error as e:
                msg.config(text=f"DB error: {e}")
                return
            dlg.destroy()
            self._refresh_list()
        save_btn = tk.Button(dlg, text="Save Secret Text", command=save)
        style_btn(save_btn)
        save_btn.pack(pady=8)

    # ── Helpers ───────────────────────────────────────────────

    def _site_icon(self, site):
        icons = {"google": "G", "github": "GH", "facebook": "FB", "twitter": "TW",
                 "amazon": "AMZ", "bank": "BANK", "netflix": "NF", "apple": "APL",
                 "microsoft": "MS", "instagram": "IG", "youtube": "YT"}
        s = site.lower()
        for k, v in icons.items():
            if k in s:
                return v
        return "KEY"

    def _logout(self):
        self.app.logged_in_user = None
        self._active_folder_id = None
        self._active_tab = "passwords"
        self.app.show("welcome")

    def on_show(self):
        user = self.app.logged_in_user
        self._user_label.config(text=f"Logged in: {user['username']}")
        self._active_folder_id = None
        self._active_tab = "passwords"
        self._build_sidebar()
        self._switch_tab("passwords")
        self._update_folder_label()


# ─────────────────────────────────────────────────────────
#  MAIN APP
# ─────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ImageVault - Image-Based Password Manager")
        self.geometry("900x640")
        self.minsize(750, 540)
        self.configure(bg=BG)
        self.logged_in_user = None

        self._screens = {
            "welcome":  WelcomeScreen(self, self),
            "register": RegisterScreen(self, self),
            "login":    LoginScreen(self, self),
            "vault":    VaultScreen(self, self),
        }
        self._current = None
        self.show("welcome")

    def show(self, name):
        if self._current:
            self._current.pack_forget()
        screen = self._screens[name]
        screen.pack(fill="both", expand=True)
        screen.on_show()
        self._current = screen


# ─────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting ImageVault...")
    print("Requirements: pip install pillow opencv-python mysql-connector-python")
    print(
        f"Connecting to MySQL at {DB_CONFIG['host']}:{DB_CONFIG['port']} ...")
    init_db()
    print("Database ready.")
    app = App()
    app.mainloop()
