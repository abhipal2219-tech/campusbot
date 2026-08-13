import google.generativeai as genai
import os

# 1. Setup API Key
os.environ["GOOGLE_API_KEY"] = "YOUR_API_KEY_HERE"
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

# 2. Upload your college data file
# This is stored for 48 hours for session use
sample_file = genai.upload_file(path="college_data.md", display_name="College Info")

# 3. Initialize model with 'retrieval' tool enabled
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    tools=[{"google_search_retrieval": {}}] # Or specific file_search tools
)

# 4. Ask a question based on the file
response = model.generate_content([sample_file, "Where is Abhishek sir's office?"])

print(response.text)
