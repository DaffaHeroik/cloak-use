"""
Microsoft To Do reader — uses MSAL token (no browser needed).
"""
import json, urllib.request, urllib.error
from auth import msal_api, msal_access_token

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def get_me():
    """Get current user info."""
    return msal_api(f"{GRAPH_BASE}/me")


def list_todo_lists():
    """List all To Do lists."""
    return msal_api(f"{GRAPH_BASE}/me/todo/lists")


def get_list(list_id):
    """Get single list details."""
    return msal_api(f"{GRAPH_BASE}/me/todo/lists/{list_id}")


def list_tasks(list_id, top=50):
    """List tasks in a list."""
    return msal_api(f"{GRAPH_BASE}/me/todo/lists/{list_id}/tasks", {"top": top})


def get_task(list_id, task_id):
    """Get single task."""
    return msal_api(f"{GRAPH_BASE}/me/todo/lists/{list_id}/tasks/{task_id}")


def list_all_tasks():
    """Get all tasks across all lists."""
    lists_resp = list_todo_lists()
    lists = lists_resp.get("value", [])
    all_tasks = []
    for lst in lists:
        try:
            tasks = list_tasks(lst["id"])
            for t in tasks.get("value", []):
                t["_list_name"] = lst.get("displayName", "")
                all_tasks.append(t)
        except Exception as e:
            all_tasks.append({"list": lst.get("displayName"), "error": str(e)})
    return {"lists": lists, "tasks": all_tasks}


def summary():
    """Quick summary: list names + task counts + overdue tasks."""
    data = list_all_tasks()
    lines = [f"Microsoft To Do — {len(data['lists'])} lists"]
    for lst in data["lists"]:
        tasks = [t for t in data["tasks"] if t.get("_list_name") == lst.get("displayName") and "error" not in t]
        overdue = [t for t in tasks if t.get("dueDateTime") and not t.get("status") == "completed"]
        lines.append(f"  {lst.get('displayName','?')}: {len(tasks)} tasks, {len(overdue)} overdue")
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Microsoft To Do ===")
    try:
        me = get_me()
        print(f"User: {me.get('displayName')} ({me.get('userPrincipalName')})")
        print()
        print(summary())
    except Exception as e:
        print(f"Error: {e}")
        print("Token might be expired — need re-auth via browser")
