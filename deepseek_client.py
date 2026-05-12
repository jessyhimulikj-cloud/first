from openai import OpenAI
import os


# 创建 DeepSeek 客户端
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


def analyze_with_ai(prompt):

    response = client.chat.completions.create(
        model="deepseek-chat",

        messages=[
            {
                "role": "system",
                "content": "你是一位专业的A股投资分析师，擅长分析技术面、基本面、估值、行业趋势。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],

        temperature=0.3
    )

    return response.choices[0].message.content