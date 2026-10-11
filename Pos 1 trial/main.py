import tkinter as tk
from database import init_db
from login import LoginWindow

def start_frontoffice(user):
    import frontoffice
    frontoffice.start(user)

def start_backoffice(user):
    import backoffice
    backoffice.start(user)

def on_login(user):
    if user["role"] == "admin":
        start_backoffice(user)
    else:
        start_frontoffice(user)

def main():
    init_db()
    root = tk.Tk()
    LoginWindow(root, on_login)
    root.mainloop()

if __name__ == "__main__":
    main()