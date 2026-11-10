"""
Gmail reader — uses Google OAuth2 token (no browser needed).
"""
import urllib.request, urllib.error, json, time
from auth import google_api, google_access_token

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def get_profile():
    """Get Gmail profile (email address, messages total)."""
    return google_api(f"{GMAIL_BASE}/profile")


def list_messages(max_results=20, q=""):
    """List messages. q = Gmail search query (from:, subject:, etc)."""
    params = {"maxResults": int(max_results)}
    if q:
        params["q"] = q
    return google_api(f"{GMAIL_BASE}/messages", params)


def get_message(msg_id, fmt="metadata"):
    """Get single message. fmt = 'full' | 'metadata' | 'minimal'."""
    return google_api(f"{GMAIL_BASE}/messages/{msg_id}", {"format": fmt})


def get_thread(thread_id):
    """Get full thread."""
    return google_api(f"{GMAIL_BASE}/threads/{thread_id}")


def batch_read(max_results=50, q=""):
    """Read messages + parse headers. Returns list of dicts."""
    result = list_messages(max_results=max_results, q=q)
    messages = result.get("messages", [])
    out = []
    for m in messages:
        try:
            full = get_message(m["id"], fmt="metadata")
            headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
            out.append({
                "id": m["id"],
                "thread_id": full.get("threadId"),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", "(no subject)"),
                "date": headers.get("Date", ""),
                "snippet": full.get("snippet", "")[:120],
                "labels": full.get("labelIds", []),
                "unread": "UNREAD" in full.get("labelIds", []),
            })
        except Exception as e:
            out.append({"id": m["id"], "error": str(e)})
    return out


def inbox_summary(max_results=10):
    """Quick inbox summary: from, subject, date, unread."""
    return batch_read(max_results=max_results, q="in:inbox")


def search(query, max_results=20):
    """Search Gmail."""
    return batch_read(max_results=max_results, q=query)


if __name__ == "__main__":
    # Test
    print("=== Gmail Profile ===")
    p = get_profile()
    print(f"Email: {p.get('emailAddress')}")
    print(f"Total messages: {p.get('messagesTotal')}")
    print()
    print("=== Inbox (10 latest) ===")
    for m in inbox_summary(10):
        unread = "🔴" if m.get("unread") else "  "
        print(f"{unread} {m.get('from','?')[:40]:40} | {m.get('subject','(no subject)')[:40]}")
        print(f"    {m.get('date','')[:30]} | {m.get('snippet','')[:60]}")
