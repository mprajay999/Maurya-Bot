#!/usr/bin/env python3
import os
import requests
import json

# Load .env file
def load_env_file():
    env_path = '/Users/mprajay999/Maurya Bot/.env'
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        os.environ[key] = value

load_env_file()

api_key = os.getenv("OpenAI_API_Key")

if not api_key:
    print("❌ API key not found!")
    exit(1)

print("✅ API key loaded")

# Simulate the exact request from the app
messages = [
    {
        "role": "user",
        "content": "What is the total inventory in tons?"
    }
]

print(f"📤 Sending request with {len(messages)} messages...")

response = requests.post(
    "https://api.openai.com/v1/chat/completions",
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    },
    json={
        "model": "gpt-4-turbo",
        "max_tokens": 2000,
        "messages": messages
    },
    timeout=30
)

print(f"📡 Response status: {response.status_code}")

if response.status_code == 200:
    result = response.json()
    reply = result['choices'][0]['message']['content']
    print(f"✅ Success!")
    print(f"💬 Reply:\n{reply}")
else:
    print(f"❌ Error: {response.status_code}")
    print(f"Response:\n{response.text}")
