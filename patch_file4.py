import re

with open("backend/tests/unit/test_lock_bypass_fixes.py", "r") as f:
    data = f.read()

data = data.replace(
    """class TestPromptDataLockFilter:
    \"\"\"get_prompt_data (shared utility) must exclude locked memories.\"\"\"

    @pytest.fixture(autouse=True)
    def clear_cache(self, mem_module):
        if hasattr(mem_module, "_prompt_data_cache"):
            mem_module._prompt_data_cache.clear()""",
    """class TestPromptDataLockFilter:
    \"\"\"get_prompt_data (shared utility) must exclude locked memories.\"\"\"

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        import sys
        if 'utils.llms.memory' in sys.modules:
            mod = sys.modules['utils.llms.memory']
            if hasattr(mod, '_prompt_data_cache'):
                mod._prompt_data_cache.clear()""",
)

with open("backend/tests/unit/test_lock_bypass_fixes.py", "w") as f:
    f.write(data)
