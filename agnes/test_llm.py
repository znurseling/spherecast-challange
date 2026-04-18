from app.llm import understand_message
from app.config import LLM_ENABLED
print(f"LLM Enabled: {LLM_ENABLED}")
print(understand_message("how many raw materials do we have"))
print(understand_message("how many items in inventory"))
print(understand_message("how many ingredients do we use"))
