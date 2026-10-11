import tkinter as tk
from tkinter import messagebox
from database import authenticate

class LoginWindow:
    def __init__(self, root, on_success):
        self.root = root
        self.on_success = on_success
        self.root.title("POS - Login")
        self.root.geometry("360x300")
        self.root.configure(bg="#1e293b")
        self.build()

    def build(self):
        tk.Label(self.root, text="POS System", font=("Segoe UI", 20, "bold"),
                 bg="#1e293b", fg="white").pack(pady=(30, 20))

        frame = tk.Frame(self.root, bg="white", padx=20, pady=20)
        frame.pack(padx=30, fill="x")

        tk.Label(frame, text="Username", bg="white").pack(anchor="w")
        self.user = tk.Entry(frame, font=("Segoe UI", 11))
        self.user.pack(fill="x", pady=(0, 10))
        self.user.insert(0, "admin")

        tk.Label(frame, text="Password", bg="white").pack(anchor="w")
        self.pwd = tk.Entry(frame, show="*", font=("Segoe UI", 11))
        self.pwd.pack(fill="x", pady=(0, 15))
        self.pwd.insert(0, "admin")

        tk.Button(frame, text="Login", bg="#3b82f6", fg="white",
                  font=("Segoe UI", 11, "bold"), relief="flat",
                  command=self.login).pack(fill="x", ipady=6)

        tk.Label(self.root, text="admin/admin  ·  cashier/1234",
                 bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 9)).pack(pady=10)

        self.root.bind("<Return>", lambda e: self.login())

    def login(self):
        u = self.user.get().strip()
        p = self.pwd.get().strip()
        user = authenticate(u, p)
        if not user:
            messagebox.showerror("Login Failed", "Invalid username or password")
            return
        self.root.destroy()
        self.on_success(user)