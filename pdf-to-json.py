from google import genai
from google.genai import types
import pathlib
import os

api_key = os.environ.get("GOOGLE_API_KEY")
if (api_key is None):
    raise Exception("API Key not found")

client = genai.Client(api_key=api_key)

# Retrieve and encode the PDF byte
filepath = pathlib.Path('file.pdf')

prompt = "Summarize this document"
response = client.models.generate_content(
  model="gemini-2.0-flash",
  contents=[
      types.Part.from_bytes(
        data=filepath.read_bytes(),
        mime_type='application/pdf',
      ),
      prompt])

# TODO: alle pdfs aus pdf_files nacheinander, structured output, pdf json abspeichern, nur neue pdfs abfragen