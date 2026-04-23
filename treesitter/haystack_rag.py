from haystack.components.generators.openai import OpenAIGenerator
from haystack.utils import Secret
from haystack.dataclasses import ChatMessage

# 建立地端 LLM 產生器
# 注意：即使是地端，有時仍需填入虛擬的 api_key
client = OpenAIGenerator(
    api_key=Secret.from_token("any-string-will-do"), 
    model="gpt-oss-20b", # 例如 llama3 或 deepseek-coder
    api_base_url="http://127.0.0.1:8000/v1/" # 指向你的 SSH Tunnel 端口
)

response = client.run("When was the first version of Haystack released?")

print(response)