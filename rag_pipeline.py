import os
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings
from langchain.prompts import PromptTemplate
import requests
import json

load_dotenv()

class RAGPipeline:
    def __init__(self):
        self.embedder = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        self.client = chromadb.PersistentClient(path=os.getenv("CHROMA_DB_PATH", "./chroma_db"))
        self.collection = self.client.get_or_create_collection(name="finance_kb")
        self.xai_api_key = os.getenv("XAI_API_KEY")
        self.prompt_template = PromptTemplate(
            input_variables=["context", "question", "history"],
            template="You are a finance SME. Use the context: {context}\nHistory: {history}\nQuestion: {question}\nRespond concisely in the detected language."
        )
        self.load_kb_docs()  # Load on init

    def load_kb_docs(self):
        kb_path = "./kb"
        if os.path.exists(kb_path):
            docs = []
            for file in os.listdir(kb_path):
                if file.endswith('.txt'):
                    with open(os.path.join(kb_path, file), 'r', encoding='utf-8') as f:
                        docs.append(f.read())
            if docs:
                embeddings = self.embedder.encode(docs).tolist()
                ids = [f"doc_{i}" for i in range(len(docs))]
                self.collection.add(documents=docs, embeddings=embeddings, ids=ids)
                print(f"Loaded {len(docs)} KB docs into ChromaDB")
            else:
                print("No KB files found in ./kb")
        else:
            print("KB folder not found - create ./kb with .txt files")

    def retrieve(self, query: str, k: int = 5) -> str:
        query_embedding = self.embedder.encode([query]).tolist()[0]
        results = self.collection.query(query_embeddings=[query_embedding], n_results=k)
        return "\n".join([doc for doc in results['documents'][0]]) if results['documents'] else "No relevant finance data found."

    def generate(self, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self.xai_api_key}", "Content-Type": "application/json"}
        data = {
            "model": "grok-4-fast",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1000,
            "temperature": 0.7
        }
        response = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=data)
        return response.json()["choices"][0]["message"]["content"]

    def retrieve_and_generate(self, query: str, history: list, lang: str) -> dict:
        context = self.retrieve(query)
        history_str = "\n".join([f"User: {h['input']}\nSME: {h['output']}" for h in history])
        prompt = self.prompt_template.format(context=context, question=query, history=history_str)
        print(f"Query: {query}, Context: {context[:100]}...")  # Log for debug
        response = self.generate(prompt)
        return {"response": response, "sources": context, "lang": lang}

# Init KB (run once; assume docs loaded)
def load_kb_docs(docs: list):
    embeddings = RAGPipeline().embedder.encode(docs).tolist()
    ids = [f"doc_{i}" for i in range(len(docs))]
    RAGPipeline().collection.add(documents=docs, embeddings=embeddings, ids=ids)
