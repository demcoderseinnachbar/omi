import json
from pathlib import Path
from types import ModuleType

from testing.import_isolation import load_module_fresh, stub_modules

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'web.py'


def _load_web_module() -> ModuleType:
    client = ModuleType('database._client')
    client.get_users_uid = lambda: []
    client.db = None
    with stub_modules({'database._client': client}):
        return load_module_fresh('web_persona_export', str(_SCRIPT))


def test_map_plugin_data_by_persona_name_groups_messages_and_injects_uid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'user_messages_with_bot_name.json').write_text(
        json.dumps(
            {
                'uid-1': [{'botName': 'Coach', 'text': 'first'}],
                'uid-2': [{'botName': 'Coach', 'text': 'second'}, {'text': 'ignored'}],
            }
        ),
        encoding='utf-8',
    )

    _load_web_module().map_plugin_data_by_persona_name()

    assert json.loads((tmp_path / 'plugin_data_by_persona_name.json').read_text(encoding='utf-8')) == {
        'Coach': [
            {'botName': 'Coach', 'text': 'first', 'uid': 'uid-1'},
            {'botName': 'Coach', 'text': 'second', 'uid': 'uid-2'},
        ]
    }


def test_map_plugin_data_by_persona_name_handles_missing_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    _load_web_module().map_plugin_data_by_persona_name()

    assert not (tmp_path / 'plugin_data_by_persona_name.json').exists()
