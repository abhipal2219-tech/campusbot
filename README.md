
# 🏫 UEM Kolkata Campus Bot

A well-organized, modular chatbot system for UEM Kolkata campus navigation and information.

## 📁 Project Structure

- `index.html`: The main unified chatbot interface.
- `css/`: Modern styles for the chatbot.
- `js/`: Modular JavaScript logic.
  - `vector-store.js`: Local TF-IDF search engine.
  - `search-engine.js`: Data processing and search logic.
  - `chatbot-ui.js`: Interactive UI controller.
- `data/`: Centralized JSON datasets.
  - `faculty.json`: Faculty details, cabins, and codes.
  - `rooms.json`: Room allocations across all blocks.
  - `sections.json`: Section locations and class teacher details.
- `python/`: Backend scripts for RAG (Retrieval-Augmented Generation).
  - `campus_rag_bot.py`: CLI-based RAG chatbot.
  - `knowledge_base.py`: Logic to build the vector store from JSON data.
  - `vector_store.py`: Core TF-IDF implementation.

## 🚀 Getting Started

### Web Interface
Simply open `index.html` in any modern web browser. The bot works entirely offline using the pre-loaded JSON data and a local vector search engine.

### Python CLI Bot
1. Navigate to the `python/` directory.
2. Run `python campus_rag_bot.py`.
3. Ask questions like "Where is Section G?" or "Who is the mentor for Section A?".

## 🛠️ Data Updates
To update campus information, edit the files in the `data/` directory. Both the web interface and the Python bot will automatically use the updated data.
