"""
Session manager — save/restore cookies so login happens once.
"""
from vault import get_session, save_session
import cloak


def restore_session(domain: str):
    """Restore saved cookies for a domain."""
    session = get_session(domain)
    if not session:
        return False

    cookies = session.get("cookies", [])
    if not cookies:
        return False

    # Set cookies via CDP
    for cookie in cookies:
        try:
            cloak.send('Network.setCookie', {
                'url': f"https://{cookie.get('domain', '').lstrip('.')}",
                'name': cookie['name'],
                'value': cookie['value'],
                'domain': cookie.get('domain', ''),
                'path': cookie.get('path', '/'),
                'secure': cookie.get('secure', False),
                'httpOnly': cookie.get('httpOnly', False),
                'sameSite': cookie.get('sameSite', 'Lax'),
                'expires': cookie.get('expires', -1),
            }, timeout=5)
        except Exception:
            pass

    return True

def save_current_session(domain: str):
    """Save current browser session cookies."""
    try:
        cookies = cloak.send('Network.getAllCookies', timeout=10).get('cookies', [])
        # Filter only relevant cookies
        relevant = [c for c in cookies if domain in c.get('domain', '') or c.get('domain', '') in domain]
        save_session(domain, relevant)
        return True
    except Exception:
        return False

def is_session_valid(domain: str):
    """Check if saved session is still valid."""
    session = get_session(domain)
    if not session:
        return False
    
    saved_at = session.get("saved_at", "")
    if not saved_at:
        return False
    
    try:
        from datetime import datetime
        age = (datetime.utcnow() - datetime.fromisoformat(saved_at)).total_seconds()
        return age < (7 * 24 * 3600)  # 7 days
    except Exception:
        return False
