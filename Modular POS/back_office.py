"""
Launcher for the Back Office app.

Logs in via LoginWindow, then constructs BackOffice() and stores the
logged-in user's details on it before entering the main loop.
"""

from common.login import LoginWindow
from backoffice.main_app import BackOffice


def launch_backoffice(user_info):
    """Called once login succeeds.

    `user_info` is the dict produced by LoginWindow:
        {username, password, full_name, branch, role, kind}
    """
    app = BackOffice()

    # Credentials used by admin-gated actions (add product, approve LPO).
    app.admin_credentials = (user_info.get("username"),
                             user_info.get("password"))

    # Identity of the logged-in user, shown in the status line.
    app.current_user = {
        "username": user_info.get("username"),
        "full_name": user_info.get("full_name") or user_info.get("username"),
        "branch": user_info.get("branch"),
        "role": user_info.get("role") or "staff",
        "kind": user_info.get("kind") or "user",
    }
    # Refresh the status line now that the identity is known.
    try:
        app._update_user_status()
    except Exception:
        pass

    app.mainloop()


if __name__ == "__main__":
    LoginWindow(
        on_success=launch_backoffice,
        app_title="Back Office Login",
        subtitle="Evans Shop — Point of Sale",
    ).mainloop()