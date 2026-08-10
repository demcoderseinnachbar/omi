import re

with open("backend/tests/unit/test_baseline_memories.py", "r") as f:
    data = f.read()

data = data.replace(
"""class TestBaselineMemoryInjection:
    \"\"\"
    Each test patches exactly the three callables that get_prompt_data uses at runtime:""",
"""class TestBaselineMemoryInjection:
    @pytest.fixture(autouse=True)
    def clear_cache(self, mem_module):
        if hasattr(mem_module, "_prompt_data_cache"):
            mem_module._prompt_data_cache.clear()

    \"\"\"
    Each test patches exactly the three callables that get_prompt_data uses at runtime:"""
)

with open("backend/tests/unit/test_baseline_memories.py", "w") as f:
    f.write(data)


with open("backend/tests/unit/test_lock_bypass_fixes.py", "r") as f:
    data2 = f.read()

data2 = data2.replace(
"""class TestPromptDataLockFilter:
    \"\"\"get_prompt_data (shared utility) must exclude locked memories.\"\"\"

    def test_get_prompt_data_filters_locked_memories(self):""",
"""class TestPromptDataLockFilter:
    \"\"\"get_prompt_data (shared utility) must exclude locked memories.\"\"\"

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from utils.llms.memory import _prompt_data_cache
        _prompt_data_cache.clear()

    def test_get_prompt_data_filters_locked_memories(self):"""
)

with open("backend/tests/unit/test_lock_bypass_fixes.py", "w") as f:
    f.write(data2)
