import os
from dotenv import load_dotenv

load_dotenv()

api_name = os.environ["API_NAME"]
api_key = os.environ["API_KEY"]

turn_url = os.environ["HF_URL"]
turn_token = os.environ["HF_TOKEN"]

groq_key = os.environ["GROQ_KEY"]
