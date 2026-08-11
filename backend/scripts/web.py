from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, cast

from database._client import get_users_uid, db


import json

USER_BATCH_SIZE = 20


def get_user_messages_with_bot_name() -> List[str]:
    user_messages_with_bot_name: Dict[str, List[Dict[str, Any]]] = {}
    uids = get_users_uid()
    users_ref = db.collection("users")
    print(len(uids))

    def process_user(uid: str) -> None:
        messages_ref = users_ref.document(uid).collection("messages")
        messages = messages_ref.stream()
        filtered_messages: List[Dict[str, Any]] = []
        for message in messages:
            raw: object = message.to_dict()
            data: Dict[str, Any] = cast(Dict[str, Any], raw) if isinstance(raw, dict) else {}
            if 'botName' in data:
                filtered_messages.append(data)
        print(uid, "has personas messages", len(filtered_messages))
        if filtered_messages:
            user_messages_with_bot_name[uid] = filtered_messages

    for start in range(0, len(uids), USER_BATCH_SIZE):
        with ThreadPoolExecutor(max_workers=USER_BATCH_SIZE) as executor:
            list(executor.map(process_user, uids[start : start + USER_BATCH_SIZE]))

    with open("user_messages_with_bot_name.json", "w") as f:
        json.dump(user_messages_with_bot_name, f, default=str)

    return uids


def map_plugin_data_by_persona_name() -> None:
    try:
        with open("user_messages_with_bot_name.json", "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        print("user_messages_with_bot_name.json not found. Run get_user_messages_with_bot_name() first.")
        return

    persona_uids: Dict[str, set[str]] = {}

    for uid, messages in data.items():
        for message in messages:
            bot_name = message.get("botName")
            if bot_name:
                persona_uids.setdefault(bot_name, set()).add(uid)

    plugin_data_by_persona: Dict[str, List[Dict[str, Any]]] = {}
    for plugin_document in db.collection("plugins_data").stream():
        raw: object = plugin_document.to_dict()
        plugin_data: Dict[str, Any] = cast(Dict[str, Any], raw) if isinstance(raw, dict) else {}
        persona_name = plugin_data.get("name")
        if not isinstance(persona_name, str) or persona_name not in persona_uids:
            continue
        for uid in sorted(persona_uids[persona_name]):
            # Include uid in the mapped data to keep track of who the message belongs to
            plugin_data_with_uid = plugin_data.copy()
            plugin_data_with_uid["uid"] = uid
            plugin_data_by_persona.setdefault(persona_name, []).append(plugin_data_with_uid)

    with open("plugin_data_by_persona_name.json", "w") as f:
        json.dump(plugin_data_by_persona, f, indent=2, default=str)

    print(f"Mapped {len(plugin_data_by_persona)} personas to plugin_data_by_persona_name.json")


if __name__ == "__main__":
    get_user_messages_with_bot_name()
    map_plugin_data_by_persona_name()
    # TODO: questions
    # -- % of people who provided their x vs someone else's, and most popular questions
    # -- If someone else, who were the top 3 most popular questions and to whom
    # - how many users have personas messages?
    # - how many conversations are just automatic messages? (no user messages)
    # - how many users have no messages back at all? ratio
    # - conversations length distribution
    # - # of conversations distribution per user
